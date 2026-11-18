import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from metis.blue.runtime.providers import CLIProvider
from metis.blue.runtime.store import Store


class ProviderTests(unittest.TestCase):
    def test_real_subprocess_protocol_and_usage(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            script=folder/'provider.py'
            script.write_text('import sys,json\np=sys.stdin.read()\nprint(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"Evidence received"}}))\nprint(json.dumps({"type":"turn.completed","usage":{"input_tokens":20,"cached_input_tokens":10,"output_tokens":3}}))\n')
            store=Store(folder/'state.db');run,_=store.new_run('fixture')
            with patch('metis.blue.runtime.providers.executable',return_value=sys.executable):engine=CLIProvider('codex',timeout=5)
            with patch.object(engine,'command',return_value=[sys.executable,str(script)]):
                result=engine.call('Synthetic evidence',store,run,'worker')
            self.assertEqual(result['text'],'Evidence received')
            self.assertEqual(store.report(run)['totals']['total'],23)
            self.assertTrue(store.report(run)['usage_coverage']['total_complete'])
            self.assertFalse(store.report(run)['usage_coverage']['complete'])

    def test_timeout_is_bounded_and_does_not_claim_completion(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/'state.db');run,_=store.new_run('fixture')
            with patch('metis.blue.runtime.providers.executable',return_value=sys.executable):engine=CLIProvider('codex',timeout=0.05)
            with patch.object(engine,'command',return_value=[sys.executable,'-c','import time; time.sleep(10)']):
                with self.assertRaisesRegex(RuntimeError,'time limit'):engine.call('fixture',store,run,'worker')
            report=store.report(run)
            self.assertFalse(report['usage_coverage']['complete'])
            self.assertEqual(report['usage_coverage']['missing_agents'],['worker'])

    def test_owner_capacity_change_respects_current_leases(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td)/'state.db');run,token=store.new_run('fixture')
            store.configure(run,token,{'siem':2})
            store.add_tasks(run,token,[{'id':'a','prompt':'fixture','skill':'soc-triage','resources':{'siem':2}}])
            store.claim(run,token,'worker')
            with self.assertRaises(ValueError):store.resize(run,token,'siem',1)
            with self.assertRaises(PermissionError):store.resize(run,'invalid','siem',3)
            store.resize(run,token,'siem',3)
            with store.connect() as db:self.assertEqual(db.execute('SELECT capacity FROM resources WHERE name="siem"').fetchone()[0],3)

if __name__=='__main__':unittest.main()

class PrivacyTests(unittest.TestCase):
    def test_nested_json_secret_values(self):
        from metis.blue.runtime.store import redact
        result=json.loads(redact(json.dumps({'tool_result':{'access_token':'value-not-in-environment','password':'sensitive'},'usage':{'input_tokens':10}})))
        self.assertEqual(result['tool_result']['access_token'],'[REDACTED]')
        self.assertEqual(result['tool_result']['password'],'[REDACTED]')
        self.assertEqual(result['usage']['input_tokens'],10)
