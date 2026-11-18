import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from metis.blue.connections import build, execute
from metis.blue.runtime.pool import Pool, available_workers, validate_plan
from metis.blue.runtime.providers import MockProvider, extract, normalize_usage
from metis.blue.runtime.store import Store
from metis.blue.runtime.transcripts import ingest
from metis.blue.runtime.viewer import render


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=Store(self.root/'state.db');self.run,self.token=self.store.new_run('Synthetic investigation')
        self.store.configure(self.run,self.token,{'siem':1,'vm':1})
    def tearDown(self):self.tmp.cleanup()
    def task(self,name,resources=None,deps=None):
        return {'id':name,'prompt':'Analyze synthetic evidence','skill':'soc-triage','resources':resources or {},'depends_on':deps or []}
    def add(self,tasks):self.store.add_tasks(self.run,self.token,validate_plan({'tasks':tasks}))

    def test_atomic_resource_claim_under_race(self):
        self.add([self.task(str(i),{'siem':1,'vm':1}) for i in range(20)])
        with ThreadPoolExecutor(max_workers=12) as executor:
            results=list(executor.map(lambda _:self.store.claim(self.run,self.token,'w'),range(20)))
        self.assertEqual(sum(x is not None for x in results),1)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM leases').fetchone()[0],2)

    def test_other_run_shares_limits(self):
        self.add([self.task('a',{'siem':1})]);self.store.claim(self.run,self.token,'one')
        run,token=self.store.new_run('other');self.store.configure(run,token,{'siem':1})
        self.store.add_tasks(run,token,[self.task('b',{'siem':1})])
        self.assertIsNone(self.store.claim(run,token,'two'))
        self.store.finish(self.run,self.token,'a','done')
        self.assertEqual(self.store.claim(run,token,'two')['id'],'b')

    def test_no_partial_lease_or_head_of_line_blocking(self):
        self.add([self.task('hold',{'siem':1}),self.task('wait',{'siem':1,'vm':1}),self.task('ready',{'vm':1})])
        self.assertEqual(self.store.claim(self.run,self.token,'one')['id'],'hold')
        self.assertEqual(self.store.claim(self.run,self.token,'two')['id'],'ready')

    def test_pool_refills_and_enforces_limits(self):
        self.add([self.task('slow',{'siem':1}),self.task('next',{'siem':1}),self.task('fast'),self.task('refill')])
        lock=threading.Lock();intervals={}
        class Fake:
            def call(_,prompt,store,run,task):
                with lock:intervals[task]=[time.monotonic(),None]
                time.sleep(0.15 if task=='slow' else 0.02)
                with lock:intervals[task][1]=time.monotonic()
                return {'text':'Evidence pending; synthetic test only'}
        Pool(self.store,self.run,self.token,Fake(),workers=2).run_all()
        self.assertLess(intervals['refill'][0],intervals['slow'][1])
        self.assertGreaterEqual(intervals['next'][0],intervals['slow'][1])
        self.assertEqual(self.store.report(self.run)['run']['status'],'completed')

    def test_failure_blocks_dependents(self):
        self.add([self.task('a'),self.task('b',deps=['a'])])
        class Failed:
            def call(self,*args):raise RuntimeError('missing evidence')
        Pool(self.store,self.run,self.token,Failed(),workers=2).run_all()
        self.assertEqual([t['state'] for t in self.store.tasks(self.run)],['failed','blocked'])

    def test_resource_wait_keeps_pending_and_does_not_expire(self):
        self.add([self.task('a',{'siem':1}),self.task('b',{'siem':1})])
        self.store.claim(self.run,self.token,'previous')
        Pool(self.store,self.run,self.token,MockProvider(),wait_seconds=0.05).run_all()
        self.assertEqual(self.store.report(self.run)['run']['status'],'waiting')
        self.assertEqual([t['state'] for t in self.store.tasks(self.run)],['running','pending'])

    def test_grant_scope_expiry_and_single_use(self):
        self.add([self.task('a')])
        with self.assertRaises(PermissionError):self.store.grant(self.run,'bad','a','vm','open','user approved')
        gid=self.store.grant(self.run,self.token,'a','vm','open','user approved',ttl=5)
        with self.assertRaises(PermissionError):self.store.consume_grant(self.run,'a','vm','delete',gid)
        self.store.consume_grant(self.run,'a','vm','open',gid)
        with self.assertRaises(PermissionError):self.store.consume_grant(self.run,'a','vm','open',gid)
        gid=self.store.grant(self.run,self.token,'a','vm','open','user approved',ttl=0.01)
        time.sleep(0.02)
        with self.assertRaises(PermissionError):self.store.consume_grant(self.run,'a','vm','open',gid)

    def test_concurrent_grant_consumption(self):
        self.add([self.task('a')]);gid=self.store.grant(self.run,self.token,'a','vm','open','approved')
        def consume(_):
            try:self.store.consume_grant(self.run,'a','vm','open',gid);return True
            except PermissionError:return False
        with ThreadPoolExecutor(max_workers=8) as pool:self.assertEqual(sum(pool.map(consume,range(8))),1)

    def test_invalid_plan_and_resource_rollback(self):
        for tasks in ([self.task('a',deps=['missing'])],[self.task('a',deps=['b']),self.task('b',deps=['a'])],[self.task('a'),self.task('a')]):
            with self.assertRaises(ValueError):validate_plan({'tasks':tasks})
        with self.assertRaises(ValueError):self.add([self.task('ok'),self.task('bad',{'siem':2})])
        self.assertEqual(self.store.tasks(self.run),[])

    def test_limit_intersection(self):
        with patch('os.cpu_count',return_value=16):
            self.assertEqual(available_workers(12,6,4),4)
            with self.assertRaises(ValueError):available_workers(0,4)

    def test_claude_usage_dedup_and_result_precedence(self):
        events=[{'type':'assistant','message':{'id':'m1','usage':{'input_tokens':10,'output_tokens':2},'content':[]}}]*2
        self.assertEqual(sum(x['input'] for x in extract('claude',events)['usage'].values()),10)
        events.append({'type':'result','result':'ok','usage':{'input_tokens':12,'output_tokens':4,'cache_read_input_tokens':30,'cache_creation_input_tokens':5}})
        values=extract('claude',events)['usage'];self.assertEqual(len(values),1)
        self.assertEqual(values['result'],{'input':12,'output':4,'cache_read':30,'cache_write':5,'input_total':47})

    def test_codex_cached_input_not_double_counted(self):
        self.assertEqual(normalize_usage('codex',{'input_tokens':100,'cached_input_tokens':90,'output_tokens':5}),{'input':10,'cache_read':90,'output':5,'cache_write':None,'input_total':100})

    def test_transcript_import_idempotent_and_native_totals(self):
        path=self.root/'trace.jsonl'
        events=[{'type':'event_msg','payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':100,'cached_input_tokens':80,'output_tokens':7}}}}, {'type':'event_msg','payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':150,'cached_input_tokens':120,'output_tokens':9}}}}]
        path.write_text('\n'.join(json.dumps(e) for e in events))
        ingest(self.store,self.run,'owner',path,'codex');ingest(self.store,self.run,'owner',path,'codex')
        self.assertEqual(self.store.report(self.run)['totals']['total'],159)
        self.assertEqual(len(self.store.report(self.run)['usage']),1)

    def test_secret_redaction_and_viewer_escaping(self):
        with patch.dict(os.environ,{'SVC_PASSWORD':'a-secret-value'}):
            self.store.message(self.run,None,'owner','user','note','a-secret-value <script>alert(1)</script> password=another-secret')
        data=self.store.report(self.run)
        self.assertNotIn('a-secret-value',json.dumps(data));self.assertNotIn('another-secret',json.dumps(data))
        page=render(data);self.assertNotIn('<script>',page);self.assertIn('&lt;script&gt;',page)

    def test_ssh_read_profile_and_secret_argument_hygiene(self):
        with patch.dict(os.environ,{'LOGIN_PASSWORD':'synthetic-password'}):
            result=build({'protocol':'ssh','host':'192.0.2.10','password_env':'LOGIN_PASSWORD'},'system')
        self.assertNotIn('synthetic-password',' '.join(result['argv']))
        self.assertEqual(result['env']['SSHPASS'],'synthetic-password')
        self.assertFalse(result['write'])
        with self.assertRaises(ValueError):build({'protocol':'ssh','host':'-oProxyCommand=bad'},'system')
        with self.assertRaises(ValueError):build({'protocol':'ssh','host':'192.0.2.10'},'arbitrary-shell')

    def test_connection_requires_lease_and_write_grant(self):
        config={'protocol':'rdp','host':'192.0.2.10','resource':'vm'}
        self.add([self.task('a',{'vm':1})])
        with self.assertRaises(PermissionError):execute(self.store,self.run,'a',config,'open')
        self.store.claim(self.run,self.token,'worker')
        with self.assertRaises(PermissionError):execute(self.store,self.run,'a',config,'open')
        gid=self.store.grant(self.run,self.token,'a','vm','open','user approved')
        import sys
        spec=build(config,'open');spec['argv']=[sys.executable,'-c','print("connected")']
        with patch('metis.blue.connections.build',return_value=spec):
            self.assertEqual(execute(self.store,self.run,'a',config,'open',gid)['returncode'],0)

    def test_every_protocol_plan(self):
        self.assertFalse(build({'protocol':'vnc','host':'192.0.2.10'},'view')['write'])
        self.assertTrue(build({'protocol':'vnc','host':'192.0.2.10'},'control')['write'])
        socks=build({'protocol':'socks','host':'192.0.2.10'},'start')
        self.assertIn('127.0.0.1:1080',socks['argv'])
        vpn=self.root/'profile.conf';vpn.write_text('client\n')
        self.assertTrue(build({'protocol':'vpn','config_file':str(vpn)},'start')['write'])
        self.assertFalse(build({'protocol':'browser','url':'https://example.invalid'},'view')['write'])

if __name__=='__main__':unittest.main()

class StructuredOutputTests(unittest.TestCase):
    def test_preface_and_one_fenced_json(self):
        from metis.blue.runtime.providers import parse_json
        self.assertEqual(parse_json('Result follows.\n```json\n{"ok":true}\n```\nExplanation.'),{'ok':True})
        with self.assertRaises(ValueError):parse_json('```json\n{"a":1}\n```\n```json\n{"a":2}\n```')
    def test_private_thinking_is_not_logged(self):
        event={'type':'assistant','message':{'id':'m','content':[{'type':'thinking','thinking':'private reasoning'},{'type':'text','text':'public result'}]}}
        output=extract('claude',[event])
        self.assertNotIn('private reasoning',str(output['messages']))
        self.assertIn('public result',str(output['messages']))
