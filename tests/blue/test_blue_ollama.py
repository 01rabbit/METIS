import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from metis.blue.runtime.ollama import OllamaClient
from metis.blue.runtime.store import Store


class OllamaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'db')
        self.run,_=self.store.new_run('synthetic API test');self.requests=[]
        outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                outer.requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(outer.response).encode())
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.client=OllamaClient('http://127.0.0.1:'+str(self.server.server_port))
        self.response={'done':True,'model':'test','message':{'content':'{"ok":true}','thinking':'private scratchpad'},'prompt_eval_count':20,'prompt_eval_cached_count':15,'eval_count':6}
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def test_usage_and_public_content_only(self):
        result=self.client.call('test','Synthetic question',self.store,self.run,'bundle')
        self.assertEqual(result['text'],'{"ok":true}')
        report=self.store.report(self.run)
        self.assertEqual(report['totals'],{'input': 5,'output': 6,'cache_read': 15,'cache_write': None,'input_total': 20,'total': 26})
        self.assertNotIn('private scratchpad',json.dumps(report))
        self.assertNotIn('tools',self.requests[0]);self.assertNotIn('expected',str(self.requests[0]))
        self.assertEqual(self.requests[0]['options']['num_ctx'],8192)
    def test_explicit_context_budget_preserves_the_default(self):
        client=OllamaClient(self.client.url,num_ctx=65536)
        client.call('test','Synthetic question',self.store,self.run,'bundle')
        self.assertEqual(self.requests[0]['options']['num_ctx'],65536)
        for value in (True,0,65536.0,1048577):
            with self.assertRaises(ValueError):OllamaClient(self.client.url,num_ctx=value)
    def test_missing_usage_is_unknown(self):
        self.response.pop('prompt_eval_count');self.response.pop('eval_count')
        self.client.call('test','question',self.store,self.run,'bundle')
        self.assertFalse(self.store.report(self.run)['usage_coverage']['complete'])
    def test_truncation_keeps_usage_but_is_not_success(self):
        self.response['done_reason']='length'
        with self.assertRaisesRegex(RuntimeError,'token limit'):self.client.call('test','question',self.store,self.run,'bundle')
        self.assertEqual(self.store.report(self.run)['totals']['total'],26)
    def test_no_embedded_credentials_or_path(self):
        for url in ('http://user:secret@example.invalid','http://example.invalid/api','file:///tmp/test'):
            with self.assertRaises(ValueError):OllamaClient(url)
