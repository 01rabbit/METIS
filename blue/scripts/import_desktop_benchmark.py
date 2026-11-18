#!/usr/bin/env python3
"""Score explicitly selected Desktop benchmark transcripts without copying private reasoning."""
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from metis.blue.runtime.benchmark import CASES, score
from metis.blue.runtime.cli import open_run, reports
from metis.blue.runtime.providers import ROOT, extract, parse_json
from metis.blue.runtime.store import Store
from metis.blue.runtime.transcripts import ingest

p=argparse.ArgumentParser()
p.add_argument('transcripts',nargs='+',type=Path)
p.add_argument('--round',default='baseline')
p.add_argument('--effort',default='unknown',choices=['unknown','low','medium','high','max'])
p.add_argument('--db',type=Path,default=ROOT/'.state/state.sqlite3')
args=p.parse_args()
store=Store(args.db);rows=[]
for path in args.transcripts:
    events=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    result=extract('claude',events)
    answer=parse_json(result['text'])
    checks=[score(c,answer.get(c['id'],{})) for c in CASES]
    tool_calls=[c.get('name','unknown') for e in events if isinstance(e.get('message'),dict) for c in e['message'].get('content',[]) if isinstance(c,dict) and c.get('type')=='tool_use']
    stamps=[datetime.fromisoformat(e['timestamp']) for e in events if e.get('type') in ('user','assistant') and e.get('timestamp')]
    try:json.loads(result['text']);plain_json=True
    except ValueError:plain_json=False
    run,token=open_run(store,'Desktop SOC benchmark '+args.round+': '+result['model'])
    ingest(store,run,'owner',path,'claude')
    store.status(run,token,'completed')
    row={'model':result['model'],'run':run,'round':args.round,'effort':args.effort,'protocol':'desktop-bundled','passed':sum(x['passed'] for x in checks),'total':sum(x['total'] for x in checks),'checks':checks,'plain_json':plain_json,'tool_calls':tool_calls,'seconds':round((max(stamps)-min(stamps)).total_seconds(),3) if stamps else None,'tokens':store.report(run)['totals'],'transcript_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'report':reports(store,run)}
    rows.append(row)
folder=ROOT/'.state/benchmarks';folder.mkdir(parents=True,exist_ok=True)
(folder/(args.round+'.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(rows,ensure_ascii=False,indent=2))
