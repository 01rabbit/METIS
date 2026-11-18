"""Import explicitly selected transcripts, including native session formats."""
import hashlib
import json
from pathlib import Path

from .providers import extract, normalize_usage
from .store import USAGE_COLUMNS, redact, usage_row


def ingest(store,run,task,path,provider):
    path=Path(path).resolve()
    source='import:'+hashlib.sha256(str(path).encode()).hexdigest()[:20]
    events=[];malformed=0
    for line in path.read_text().splitlines():
        if not line.strip():continue
        try:
            event=json.loads(line)
            if not isinstance(event,dict):raise ValueError('Not an object')
            events.append(event)
        except ValueError:malformed+=1
    result=extract(provider,events)
    native_total=None
    if provider=='codex':
        for event in events:
            payload=event.get('payload',{})
            if event.get('type')=='event_msg' and payload.get('type')=='token_count':
                total=payload.get('info',{}).get('total_token_usage')
                if isinstance(total,dict):native_total=total
            if event.get('type')=='response_item' and payload.get('type') in ('message','function_call','function_call_output'):
                result['messages'].append((payload.get('role','tool'),'owner',source,json.dumps(payload,ensure_ascii=False)))
        if native_total is not None:result['usage']={'session-total':normalize_usage('codex',native_total)}
    if not result['usage']:
        result['usage']={'unavailable':normalize_usage(provider,{})}
    # Replace this source atomically; importing an updated file cannot double-count it.
    with store.transaction() as db:
        if not db.execute('SELECT 1 FROM runs WHERE id=?',(run,)).fetchone():raise ValueError('Unknown run')
        db.execute('DELETE FROM usage WHERE run=? AND task=? AND source=?',(run,task,source))
        db.execute('DELETE FROM messages WHERE run=? AND task=? AND kind=?',(run,task,source))
        import time
        for sender,recipient,kind,body in result['messages']:
            db.execute('INSERT INTO messages(run,task,sender,recipient,kind,body,created) VALUES(?,?,?,?,?,?,?)',(run,task,sender,recipient,source,redact(body),time.time()))
        for event,values in result['usage'].items():
            db.execute('INSERT INTO usage ('+USAGE_COLUMNS+') VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',usage_row(run,task,source,event,result['model'],values))
    available=any(any(v is not None for v in values.values()) for values in result['usage'].values())
    return {'source':source,'messages':len(result['messages']),'usage_records':len(result['usage']),'malformed_lines':malformed,'usage_available':available}
