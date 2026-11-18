"""Unknown usage is not zero; all providers here use inert local stubs."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from metis.blue.runtime.ollama import OllamaClient
from metis.blue.runtime.providers import CLIProvider, extract, normalize_usage
from metis.blue.runtime.store import USAGE_FIELDS, Store, usage_values
from metis.blue.runtime.transcripts import ingest
from metis.blue.runtime.viewer import render


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'state.sqlite')
        self.run, _ = self.store.new_run('Synthetic usage accounting')

    def tearDown(self):
        self.tmp.cleanup()

    def test_absent_null_and_explicit_zero_are_distinct(self):
        for provider in ('codex', 'claude', 'ollama'):
            self.assertEqual(normalize_usage(provider, {}), dict.fromkeys(USAGE_FIELDS))
            self.assertEqual(normalize_usage(provider, None), dict.fromkeys(USAGE_FIELDS))
        values = normalize_usage('claude', {'input_tokens': 0, 'output_tokens': 0,
                   'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0})
        self.store.usage(self.run, 'worker', 'claude', 'zero', 'fixture', values)
        report = self.store.report(self.run)
        self.assertTrue(report['usage_coverage']['complete'])
        self.assertEqual(report['totals'], dict.fromkeys(USAGE_FIELDS + ('total',), 0))
        self.store.usage(self.run, 'worker', 'claude', 'unknown', 'fixture', {})
        report = self.store.report(self.run)
        self.assertTrue(all(v is None for v in report['totals'].values()))
        self.assertEqual(report['known_subtotals']['total'], 0)
        self.assertFalse(report['usage_coverage']['total_complete'])

    def test_provider_input_total_survives_unknown_cache(self):
        for provider, counts in [('codex', {'input_tokens': 20, 'output_tokens': 6}),
                                 ('ollama', {'prompt_eval_count': 20, 'eval_count': 6})]:
            usage = normalize_usage(provider, counts)
            self.assertIsNone(usage['input'])
            self.assertIsNone(usage['cache_read'])
            self.assertEqual(usage['input_total'], 20)
            self.store.usage(self.run, provider, provider, 'call', 'fixture', usage)
        report = self.store.report(self.run)
        self.assertEqual(report['totals']['input_total'], 40)
        self.assertEqual(report['totals']['total'], 52)
        self.assertIsNone(report['totals']['cache_read'])
        self.assertTrue(report['usage_coverage']['total_complete'])
        self.assertFalse(report['usage_coverage']['complete'])
        zero = normalize_usage('codex', {'input_tokens': 20, 'output_tokens': 6, 'cached_input_tokens': 0})
        self.assertEqual(zero['input'], 20)
        self.assertEqual(zero['cache_read'], 0)

    def test_claude_does_not_guess_missing_cache_components(self):
        usage = normalize_usage('claude', {'input_tokens': 20, 'output_tokens': 6})
        self.assertEqual(usage['input'], 20)
        self.assertIsNone(usage['input_total'])
        self.store.usage(self.run, 'worker', 'claude', 'call', 'fixture', usage)
        report = self.store.report(self.run)
        self.assertEqual(report['totals']['output'], 6)
        self.assertIsNone(report['totals']['total'])

    def test_invalid_provider_counts_and_inconsistent_components_rejected(self):
        for value in (True, -1, 1.5, '3', 2**63):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_usage('ollama', {'prompt_eval_count': value})
                with self.assertRaises(ValueError):
                    self.store.usage(self.run, 'w', 'manual', 'e', 'm', {'output': value})
        with self.assertRaises(ValueError):
            normalize_usage('codex', {'input_tokens': 2, 'cached_input_tokens': 3})
        with self.assertRaises(ValueError):
            usage_values({'input': 1, 'cache_read': 1, 'cache_write': 1, 'input_total': 4})
        with self.assertRaises(ValueError):
            usage_values({'input': 2**63-1, 'cache_read': 1, 'cache_write': 0})

    def test_empty_store_and_synthetic_usage_are_unknown(self):
        self.assertTrue(all(v is None for v in self.store.report(self.run)['totals'].values()))
        self.store.usage(self.run, 'fixture', 'mock', 'e', 'fixture', {}, measured=False)
        report = self.store.report(self.run)
        self.assertTrue(all(v is None for v in report['totals'].values()))
        self.assertEqual(report['usage_coverage']['synthetic_agents'], ['fixture'])

    def test_partial_mixed_events_propagate_unknown_without_hiding_subtotals(self):
        self.store.usage(self.run, 'worker', 'codex', 'a', 'fixture', normalize_usage('codex', {'input_tokens': 20, 'cached_input_tokens': 5, 'output_tokens': 3}))
        self.store.usage(self.run, 'worker', 'codex', 'b', 'fixture', normalize_usage('codex', {'input_tokens': 10, 'output_tokens': 2}))
        report = self.store.report(self.run)
        self.assertIsNone(report['totals']['input'])
        self.assertIsNone(report['totals']['cache_read'])
        self.assertEqual(report['totals']['total'], 35)
        self.assertEqual(report['known_subtotals']['input'], 15)
        self.assertEqual(report['known_subtotals']['cache_read'], 5)
        self.store.usage(self.run, 'worker', 'codex', 'b', 'fixture', {})
        report = self.store.report(self.run)
        self.assertIsNone(report['totals']['total'])
        self.assertEqual(report['known_subtotals']['total'], 23)
        self.assertEqual(report['usage'][0]['events'], 2)

    def test_missing_agent_keeps_existing_known_subtotal(self):
        self.store.usage(self.run, 'a', 'codex', 'e', 'fixture', normalize_usage('codex', {'input_tokens': 2, 'output_tokens': 3}))
        self.store.message(self.run, 'b', 'owner', 'b', 'dispatch', 'synthetic')
        report = self.store.report(self.run)
        self.assertIsNone(report['totals']['total'])
        self.assertEqual(report['known_subtotals']['total'], 5)
        self.assertEqual(report['usage_coverage']['missing_agents'], ['b'])

    def test_ollama_stub_preserves_partial_counts_and_each_call(self):
        client = OllamaClient()
        answer = {'done': True, 'model': 'fixture', 'message': {'content': 'inert'}, 'prompt_eval_count': 20, 'eval_count': 6}
        with patch.object(client, 'request', return_value=answer):
            client.call('fixture', 'one', self.store, self.run, 'worker')
        first = self.store.report(self.run)
        self.assertEqual(first['totals']['total'], 26)
        self.assertIsNone(first['totals']['cache_read'])
        with patch.object(client, 'request', return_value={'done': True, 'model': 'fixture', 'message': {'content': 'inert'}}):
            client.call('fixture', 'two', self.store, self.run, 'worker')
        report = self.store.report(self.run)
        self.assertIsNone(report['totals']['total'])
        self.assertEqual(report['known_subtotals']['total'], 26)
        self.assertEqual(report['usage'][0]['events'], 2)
        with patch.object(client, 'request', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                client.call('fixture', 'three', self.store, self.run, 'worker')
        self.assertEqual(self.store.report(self.run)['usage'][0]['events'], 3)

    def test_cli_two_calls_keep_missing_call_and_no_double_count(self):
        script = self.root / 'stub.py'
        script.write_text('import json,sys\nq=sys.stdin.read()\nprint(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"inert"}}))\nprint(json.dumps({"type":"turn.completed",**({"usage":{"input_tokens":20,"cached_input_tokens":0,"output_tokens":6}} if q=="one" else {})}))\n')
        with patch('metis.blue.runtime.providers.executable', return_value=sys.executable):
            engine = CLIProvider('codex', model='fixture')
        with patch.object(engine, 'command', return_value=[sys.executable, str(script)]):
            engine.call('one', self.store, self.run, 'worker')
            engine.call('two', self.store, self.run, 'worker')
        report = self.store.report(self.run)
        self.assertIsNone(report['totals']['total'])
        self.assertEqual(report['known_subtotals']['total'], 26)
        self.assertEqual(report['usage'][0]['events'], 2)

    def test_claude_snapshot_and_result_precedence_preserves_unknown_generation(self):
        known = {'input_tokens': 10, 'output_tokens': 2, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}
        events = [{'type': 'assistant', 'message': {'id': 'a', 'usage': known}},
                  {'type': 'assistant', 'message': {'id': 'b'}},
                  {'type': 'assistant', 'message': {'id': 'b', 'usage': None}},
                  {'type': 'result', 'result': 'inert', 'usage': {}}]
        usage = extract('claude', events)['usage']
        self.assertEqual(set(usage), {'a', 'b'})
        self.assertIsNone(usage['b']['output'])
        events.append({'type': 'assistant', 'message': {'id': 'b', 'usage': known}})
        events.append({'type': 'assistant', 'message': {'id': 'b', 'usage': {}}})
        usage = extract('claude', events)['usage']
        self.assertEqual(len(usage), 2)
        self.assertEqual(usage['b']['input_total'], 10)
        events.append({'type': 'result', 'result': 'inert', 'usage': {**known, 'input_tokens': 20, 'output_tokens': 4}})
        events.append({'type': 'assistant', 'message': {'id': 'a', 'usage': known}})
        self.assertEqual(set(extract('claude', events)['usage']), {'result'})

    def test_transcript_replace_keeps_partial_values_and_native_total(self):
        path = self.root / 'transcript.jsonl'
        event = {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {'total_token_usage': {'input_tokens': 20, 'output_tokens': 6}}}}
        path.write_text(json.dumps(event))
        for _ in range(2):
            self.assertTrue(ingest(self.store, self.run, 'worker', path, 'codex')['usage_available'])
        report = self.store.report(self.run)
        self.assertEqual(report['totals']['total'], 26)
        self.assertIsNone(report['totals']['cache_read'])
        self.assertEqual(report['usage'][0]['events'], 1)
        event['payload']['info']['total_token_usage'] = {}
        path.write_text(json.dumps(event))
        self.assertFalse(ingest(self.store, self.run, 'worker', path, 'codex')['usage_available'])
        self.assertIsNone(self.store.report(self.run)['totals']['total'])

    def test_import_without_any_usage_keeps_unknown_source(self):
        path = self.root / 'unmetered.jsonl'
        path.write_text(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'inert'}}))
        report = ingest(self.store, self.run, 'worker', path, 'codex')
        self.assertFalse(report['usage_available'])
        self.assertEqual(report['usage_records'], 1)
        self.assertIsNone(self.store.report(self.run)['totals']['total'])

    def test_legacy_values_preserved_but_not_reasserted_as_measured(self):
        path = self.root / 'legacy.sqlite'
        connection = sqlite3.connect(path)
        connection.execute('CREATE TABLE usage(run TEXT NOT NULL,task TEXT NOT NULL,source TEXT NOT NULL,event TEXT NOT NULL,model TEXT NOT NULL,input INTEGER NOT NULL,output INTEGER NOT NULL,cache_read INTEGER NOT NULL,cache_write INTEGER NOT NULL,measured INTEGER NOT NULL,PRIMARY KEY(run,task,source,event))')
        connection.execute('INSERT INTO usage VALUES(?,?,?,?,?,?,?,?,?,?)', ('legacy', 'worker', 'codex', '0', 'fixture', 20, 6, 0, 0, 1))
        connection.commit(); connection.close()
        for _ in range(2):
            store = Store(path)
            with store.connect() as db:
                rows = [dict(row) for row in db.execute('SELECT * FROM usage')]
                self.assertEqual(len(rows), 1)
                self.assertEqual([rows[0][x] for x in ('input', 'output', 'cache_read', 'cache_write')], [20, 6, 0, 0])
                self.assertEqual(rows[0]['provenance'], 'legacy-defaults-unknown')
                db.execute("INSERT OR IGNORE INTO runs VALUES('legacy','synthetic','completed',0,'unused')")
            report = store.report('legacy')
            self.assertIsNone(report['totals']['total'])
            self.assertEqual(report['legacy_usage'][0]['input'], 20)
            self.assertEqual(report['usage'][0]['measured'], 0)
            self.assertEqual(report['usage_coverage']['legacy_agents'], ['worker'])

    def test_viewer_distinguishes_unknown_zero_and_legacy(self):
        self.store.usage(self.run, 'worker', 'codex', 'e', 'fixture', normalize_usage('codex', {'input_tokens': 0, 'output_tokens': 0}))
        page = render(self.store.report(self.run))
        self.assertIn('<td>unknown</td>', page)
        self.assertIn('<td>0</td>', page)
        self.assertIn('Known subtotals', page)
        self.assertIn('Preserved legacy usage (unverified)', page)
        self.assertNotIn('Unmeasured fixture rows are marked 0', page)


if __name__ == '__main__':
    unittest.main()
