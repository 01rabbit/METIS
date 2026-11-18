"""CLI backends and normalized, idempotent token accounting."""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from . import BLUE_ROOT
from .store import USAGE_FIELDS, redact, sum_known, usage_values

ROOT = BLUE_ROOT


def executable(name):
    configured = os.environ.get('METIS_BLUE_' + name.upper() + '_BIN')
    if configured:
        if not Path(configured).is_file():
            raise FileNotFoundError('Configured provider executable does not exist')
        return configured
    found = shutil.which(name)
    if found:
        return found
    if name == 'claude':
        base = Path.home() / 'Library/Application Support/Claude/claude-code'
        candidates = list(base.glob('*/claude.app/Contents/MacOS/claude'))
        if candidates:
            def version(p):
                return tuple(int(x) for x in p.parents[3].name.split('.') if x.isdigit())
            return str(max(candidates,key=version))
    if name == 'codex':
        p=Path('/Applications/ChatGPT.app/Contents/Resources/codex')
        if p.is_file():return str(p)
    raise FileNotFoundError(name + ' CLI not found; set METIS_BLUE_' + name.upper() + '_BIN')


def normalize_usage(provider, usage):
    if usage is None:usage={}
    if not isinstance(usage,dict):raise ValueError('Usage must be an object or null')
    def count(key):
        value=usage.get(key)
        if value is not None and (type(value) is not int or not 0<=value<=9223372036854775807):
            raise ValueError('Invalid provider token count')
        return value
    if provider in ('codex','ollama'):
        total=count('input_tokens' if provider=='codex' else 'prompt_eval_count')
        cached=count('cached_input_tokens' if provider=='codex' else 'prompt_eval_cached_count')
        output=count('output_tokens' if provider=='codex' else 'eval_count')
        if total is not None and cached is not None and cached>total:raise ValueError('Cache count exceeds prompt input')
        return usage_values({'input':total-cached if total is not None and cached is not None else None,
                             'output':output,'cache_read':cached,'cache_write':None,'input_total':total})
    if provider!='claude':raise ValueError('Unsupported token usage provider')
    return usage_values({'input':count('input_tokens'),'output':count('output_tokens'),
                         'cache_read':count('cache_read_input_tokens'),'cache_write':count('cache_creation_input_tokens')})


def extract(provider, events):
    """Use Claude result usage OR message usage, never both; Codex turn deltas."""
    text_parts=[]; final=None; usage={}; result_usage=None; messages=[]; failed=False; model='unknown'
    for i,e in enumerate(events):
        kind=e.get('type')
        if provider == 'codex':
            if kind=='item.completed':
                item=e.get('item',{})
                if item.get('type')=='agent_message':text_parts.append(item.get('text',''))
                messages.append(('provider','owner',item.get('type','item'),json.dumps(item,ensure_ascii=False)))
            if kind=='turn.completed':
                usage[str(i)]=normalize_usage(provider,e.get('usage'))
            if kind in ('turn.failed','error'):failed=True
        else:
            msg=e.get('message',{})
            if isinstance(msg,dict) and kind in ('assistant','user'):
                model=msg.get('model',model)
                public=dict(msg)
                if isinstance(msg.get('content'),list):
                    public['content']=[c for c in msg['content'] if not isinstance(c,dict) or c.get('type') not in ('thinking','redacted_thinking')]
                messages.append((kind,'owner','provider-message',json.dumps(public,ensure_ascii=False)))
                # Duplicate transcript snapshots of the same message replace earlier usage.
                if kind=='assistant' or isinstance(msg.get('usage'),dict):
                    values=normalize_usage(provider,msg.get('usage'));key=msg.get('id',str(i))
                    if key in usage:
                        # Repeated snapshots describe one generation. Omission is not retraction.
                        values={k:v if v is not None else usage[key][k] for k,v in values.items()}
                        values['input_total']=sum_known(values[k] for k in ('input','cache_read','cache_write'))
                    usage[key]=values
                if kind=='assistant':
                    for c in msg.get('content',[]):
                        if isinstance(c,dict) and c.get('type')=='text':text_parts.append(c.get('text',''))
            if kind=='result':
                final=e.get('result') or json.dumps(e.get('structured_output',{}),ensure_ascii=False)
                if isinstance(e.get('usage'),dict):
                    values=normalize_usage(provider,e['usage'])
                    if any(v is not None for v in values.values()):result_usage={'result':values}
                if e.get('modelUsage'):
                    model=','.join(e['modelUsage'])
                failed=failed or bool(e.get('is_error'))
    return {'text':final if final is not None else '\n'.join(text_parts),'usage':result_usage if result_usage is not None else usage,'messages':messages,'failed':failed,'model':model}


class CLIProvider:
    def __init__(self, name, model=None, timeout=240, tools=True):
        self.name,self.model,self.timeout,self.tools=name,model,timeout,tools
        self.binary=executable(name)

    def command(self):
        if self.name=='codex':
            cmd=[self.binary,'exec','--json','--ephemeral','--sandbox','read-only','--color','never']
            if self.model:cmd+=['--model',self.model]
            return cmd+['-']
        cmd=[self.binary,'-p','--output-format','stream-json','--verbose','--permission-mode','dontAsk',
             '--tools','Read,Glob,Grep,WebFetch,WebSearch' if self.tools else '',
             '--strict-mcp-config','--mcp-config','{"mcpServers":{}}','--max-turns','8',
             '--setting-sources','']
        if self.model:cmd+=['--model',self.model]
        return cmd

    def call(self,prompt,store,run,task):
        store.message(run,task,'owner',task,'dispatch',prompt)
        usage_event='call-'+uuid.uuid4().hex
        usage_model=self.model or 'provider-default'
        store.usage(run,task,self.name,usage_event,usage_model,{})
        started=time.monotonic()
        # Temporary files prevent pipe deadlocks and unbounded in-memory buffering; private, removed on exit.
        with tempfile.TemporaryFile() as output,tempfile.TemporaryFile() as error:
            proc=subprocess.Popen(self.command(),cwd=str(ROOT),stdin=subprocess.PIPE,stdout=output,stderr=error,start_new_session=True)
            try:
                proc.communicate(prompt.encode(),timeout=self.timeout)
            except BaseException:
                try:os.killpg(proc.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                import sys
                if isinstance(sys.exc_info()[1],subprocess.TimeoutExpired):
                    raise RuntimeError('Provider exceeded its time limit') from None
                raise
            output.seek(0);raw=output.read(32*1024*1024)
            if output.read(1):raise RuntimeError('Provider output exceeded 32 MiB limit')
            error.seek(0);stderr=error.read(16384).decode(errors='replace')
        events=[]
        for line in raw.decode(errors='replace').splitlines():
            try:
                item=json.loads(line)
                if isinstance(item,dict):events.append(item)
            except ValueError:continue
        result=extract(self.name,events)
        for sender,recipient,kind,body in result['messages']:
            store.message(run,task,sender,recipient,kind,body)
        if result['usage']:
            values={k:sum_known(row[k] for row in result['usage'].values()) for k in USAGE_FIELDS}
            store.usage(run,task,self.name,usage_event,result['model'] if result['model']!='unknown' else usage_model,values)
        result['elapsed']=round(time.monotonic()-started,3)
        if proc.returncode or result['failed']:
            raise RuntimeError(redact(result['text'] or stderr or 'Provider failed'))
        if not result['text'].strip():raise RuntimeError('Provider returned no answer')
        return result


class MockProvider:
    name='mock'
    model='fixture-only'
    def call(self,prompt,store,run,task):
        store.message(run,task,'owner',task,'dispatch',prompt)
        time.sleep(0.015)
        store.usage(run,task,'mock','fixture','fixture-only',{},measured=False)
        return {'text':'Fixture completed. No live evidence or model inference was performed.','elapsed':0.015,'usage':{}}


def parse_json(text):
    s=text.strip()
    try:
        value=json.loads(s)
    except ValueError:
        # Native UIs sometimes add a preface despite a structured-output instruction.
        # Accept exactly one explicitly fenced object; do not guess between candidates.
        blocks=re.findall(r'```(?:json)?\s*\n(.*?)\n```',s,re.DOTALL)
        if len(blocks)!=1:
            raise ValueError('Expected one JSON object or one JSON fenced block') from None
        value=json.loads(blocks[0])
    if not isinstance(value,dict):raise ValueError('Expected a JSON object')
    return value
