"""Ollama's public chat API for evidence-only benchmarks, without tool execution."""
import json
import os
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .providers import normalize_usage


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

class OllamaClient:
    def __init__(self,url=None,timeout=180,num_predict=4096,think=None,num_ctx=8192):
        self.url=(url or os.environ.get('METIS_BLUE_OLLAMA_URL') or os.environ.get('OLLAMA_HOST') or 'http://127.0.0.1:11434').rstrip('/')
        parts=urlsplit(self.url)
        if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password or parts.path or parts.query or parts.fragment:
            raise ValueError('Ollama URL must be an HTTP(S) origin without credentials or a path')
        if timeout<=0 or num_predict<1:raise ValueError('Timeout and generation limit must be positive')
        if type(num_ctx) is not int or not 1<=num_ctx<=1048576:raise ValueError('Context limit must be an integer from 1 to 1048576')
        self.timeout,self.num_predict=timeout,num_predict
        self.num_ctx=num_ctx
        self.think=think
        self.opener=build_opener(ProxyHandler({}),NoRedirect())

    def request(self,path,payload=None):
        request=Request(self.url+path,data=json.dumps(payload).encode() if payload is not None else None,
                        headers={'Content-Type':'application/json'})
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                raw=response.read(4*1024*1024+1)
            if len(raw)>4*1024*1024:raise RuntimeError('Ollama response exceeded 4 MiB')
            result=json.loads(raw)
            if not isinstance(result,dict):raise RuntimeError('Ollama response must be an object')
            if result.get('error'):raise RuntimeError('Ollama: '+str(result['error']))
            return result
        except HTTPError as exc:
            raise RuntimeError('Ollama HTTP '+str(exc.code)+': '+exc.read(4096).decode(errors='replace')) from None
        except URLError as exc:
            raise RuntimeError('Ollama connection failed: '+str(exc.reason)) from None
        except TimeoutError:
            raise RuntimeError('Ollama timed out; server completion is unknown. Stop this batch before another request.') from None

    def inventory(self):
        return {'version':self.request('/api/version'),'models':self.request('/api/tags').get('models',[]),
                'running':self.request('/api/ps').get('models',[])}

    def call(self,model,prompt,store,run,task):
        store.message(run,task,'owner',task,'dispatch',prompt)
        usage_event='call-'+uuid.uuid4().hex
        store.usage(run,task,'ollama',usage_event,model,{})
        started=time.monotonic()
        payload={'model':model,'stream':False,'messages':[{'role':'user','content':prompt}],
                 'options':{'temperature':0,'num_predict':self.num_predict,'num_ctx':self.num_ctx}}
        if self.think is not None:payload['think']=self.think
        result=self.request('/api/chat',payload)
        elapsed=round(time.monotonic()-started,3)
        message=result.get('message',{})
        text=message.get('content','')
        store.message(run,task,model,'owner','benchmark-answer',text)
        usage=normalize_usage('ollama',result)
        store.usage(run,task,'ollama',usage_event,result.get('model',model),usage)
        metrics={key:result[key] for key in ('model','created_at','done','done_reason','total_duration','load_duration',
                 'prompt_eval_count','prompt_eval_cached_count','prompt_eval_duration','eval_count','eval_duration') if key in result}
        store.message(run,task,'ollama','owner','provider-metrics',json.dumps(metrics))
        if not result.get('done'):raise RuntimeError('Ollama returned an incomplete response')
        if result.get('done_reason')=='length':raise RuntimeError('Ollama generation reached its token limit')
        if message.get('tool_calls'):raise RuntimeError('Unexpected tool request in a no-tool benchmark')
        if not isinstance(text,str) or not text.strip():raise RuntimeError('Ollama returned no public answer')
        return {'text':text,'elapsed':elapsed,'metrics':metrics}
