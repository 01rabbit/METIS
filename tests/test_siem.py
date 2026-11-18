"""Local protocol simulations, not a certification against either SIEM product."""
import copy
import json
import os
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from metis.blue import siem
from metis.blue.ledger import ConnectionLedger


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    def handle_error(self, request, client_address):
        pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def output(self, body, status=200, headers=None):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def route(self):
        s = self.server.scenario
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        url = urlsplit(self.path)
        s['requests'].append((self.command, url.path, parse_qs(url.query), body, dict(self.headers)))
        if url.path == '/sink':
            return self.output({'unexpected': True})
        if url.path == '/services/search/jobs':
            form = parse_qs(body.decode())
            s['sid'] = form['id'][0]
            if s.get('redirect'):
                return self.output({}, 302, {'Location': '/sink'})
            if s.get('lost_submission'):
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            return self.output({'sid': s['sid']}, 201)
        if url.path.endswith('/control'):
            if s.get('cancel_failure'):
                return self.output({'error': os.environ.get('METIS_TEST_TOKEN')}, 500)
            if not s.get('cancel_still_running'):
                s['cancelled'] = True
            return self.output({'messages': []})
        if url.path.startswith('/services/search/jobs/'):
            if s.get('cancelled'):
                return self.output({}, 404)
            pending = s.get('pending', False)
            content = {'dispatchState': 'RUNNING' if pending else 'DONE', 'isDone': not pending,
                       'isFailed': False, 'isFinalized': s.get('finalized', False), 'isZombie': False,
                       'resultCount': str(len(s['rows']))}
            if s.pop('initial_parsing', False):
                content.update(dispatchState='PARSING', isDone=False)
                content.pop('resultCount')
            return self.output({'entry': [{'content': content}]})
        if url.path.endswith('/results'):
            query = parse_qs(url.query)
            offset, count = int(query['offset'][0]), int(query['count'][0])
            rows = s['rows'][offset:offset + count]
            if s.get('short_page'):
                rows = []
            return self.output({'preview': False, 'init_offset': offset if not s.get('bad_offset') else offset + 1,
                                'results': rows, 'messages': []})
        if url.path.endswith('/_search'):
            if s.get('elastic_error'):
                return self.output({'message': os.environ.get('METIS_TEST_TOKEN')}, 500)
            if s.get('oversized'):
                return self.output({'excess': 'x' * (siem.MAX_BODY + 1)})
            if 'elastic_response' in s:
                return self.output(s['elastic_response'])
            return self.output({'timed_out': False, '_shards': {'total': 1, 'successful': 1, 'failed': 0},
                                'hits': {'total': {'value': 1, 'relation': 'eq'},
                                         'hits': [{'_index': 'events', '_id': 'one', '_source': {
                                             'host': {'name': 'asset-7', 'unrequested': 'private-data'},
                                             'unrequested': 'also-private'}}]}})
        self.output({}, 404)

    do_GET = route
    do_POST = route


class SIEMTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ConnectionLedger(Path(self.tmp.name) / 'private/runtime.sqlite3')
        self.run = 'run-siem'
        self.store.broker.configure('siem', 1)
        self.store.lease_task(self.run, 'a', {'siem': 1})
        self.server = LocalServer(('127.0.0.1', 0), Handler)
        self.server.scenario = {'requests': [], 'rows': [{'_time': str(n), 'host': 'asset-7'} for n in range(3)]}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.env = patch.dict(os.environ, {'METIS_TEST_TOKEN': 'private-SIEM-test-token'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.profile = {'provider': 'splunk', 'base_url': 'http://127.0.0.1:' + str(self.server.server_port),
                        'test_only_http': True, 'token_env': 'METIS_TEST_TOKEN', 'resource': 'siem',
                        'indexes': ['events'], 'fields': ['_time', 'host', 'host.name'],
                        'max_rows': 10, 'page_size': 2, 'timeout_seconds': 1, 'poll_interval': 0.05}
        self.request = {'index': 'events', 'start': '2026-01-01T00:00:00Z', 'end': '2026-01-01T00:01:00Z',
                        'filters': {'host': 'asset-7'}, 'fields': ['_time', 'host'], 'limit': 10}

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def execute(self):
        return siem.execute(self.store, self.run, 'a', self.profile, self.request)

    def elastic(self):
        self.profile['provider'] = 'elastic'
        self.request['fields'] = ['host.name']
        self.request['filters'] = {'host.name': 'asset-7'}

    def test_splunk_paginates_and_records_only_redacted_metadata(self):
        result = self.execute()
        self.assertTrue(result['complete'])
        self.assertEqual(result['returned'], 3)
        pages = [r for r in self.server.scenario['requests'] if r[1].endswith('/results')]
        self.assertEqual([r[2]['offset'] for r in pages], [['0'], ['2']])
        submission = parse_qs(self.server.scenario['requests'][0][3].decode())
        self.assertEqual(submission['search'], ['search index="events" host="asset-7" | fields _time,host'])
        self.assertEqual(submission['enable_lookups'], ['false'])
        self.assertTrue(result['consumer_stopped'])
        self.assertNotIn(os.environ['METIS_TEST_TOKEN'], json.dumps(self.store.report(self.run)))
        self.store.finish_task(self.run, 'a')
        self.assertTrue(self.store.lease_task(self.run, 'b', {'siem': 1}))

    def test_splunk_parsing_can_precede_result_counters(self):
        self.server.scenario['initial_parsing'] = True
        result = self.execute()
        self.assertTrue(result['complete'])
        self.assertEqual(result['returned'], 3)
        self.assertFalse(any(r[1].endswith('/control') for r in self.server.scenario['requests']))
        with self.assertRaises(siem.SIEMError):
            siem.job_state({'entry': [{'content': {'dispatchState': 'DONE', 'isDone': True,
                            'isFailed': False, 'isFinalized': False, 'isZombie': False}}]})

    def test_complete_empty_is_distinct_from_partial_empty(self):
        self.server.scenario['rows'] = []
        result = self.execute()
        self.assertTrue(result['complete'])
        self.assertEqual(result['reported_total'], 0)
        self.server.scenario['finalized'] = True
        result = self.execute()
        self.assertFalse(result['complete'])
        self.assertEqual(result['status'], 'partial')
        self.assertIn('backend-partial-or-warning', result['reasons'])

    def test_result_cap_and_short_page_are_never_complete(self):
        self.request['limit'] = 2
        self.assertIn('result-limit', self.execute()['reasons'])
        self.server.scenario['short_page'] = True
        self.assertIn('invalid-or-short-result-page', self.execute()['reasons'])

    def test_page_offset_mismatch_is_detected(self):
        self.server.scenario['bad_offset'] = True
        result = self.execute()
        self.assertFalse(result['complete'])
        self.assertTrue(result['consumer_stopped'])

    def test_timeout_cancels_and_requires_confirmation(self):
        self.server.scenario['pending'] = True
        result = self.execute()
        self.assertFalse(result['complete'])
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['consumer_stopped'])
        # The final poll can hit its socket timeout before the next deadline check.
        self.assertIn(result['reasons'], [['search-deadline'], ['transport-timeout']])
        self.assertTrue(self.server.scenario['cancelled'])
        final_request = self.server.scenario['requests'][-1]
        self.assertEqual(final_request[0], 'GET')
        self.assertTrue(final_request[1].endswith('/' + self.server.scenario['sid']))
        self.store.finish_task(self.run, 'a')
        self.assertTrue(self.store.lease_task(self.run, 'b', {'siem': 1}))

    def test_cancel_acknowledgement_alone_does_not_release_consumer(self):
        self.server.scenario.update(pending=True, cancel_still_running=True)
        result = self.execute()
        self.assertFalse(result['consumer_stopped'])
        self.assertEqual(result['status'], 'indeterminate')
        with self.assertRaises(ValueError):
            self.store.finish_task(self.run, 'a')
        with self.assertRaises(PermissionError):
            self.execute()
        self.assertRaises(PermissionError, self.store.lease_task, self.run, 'b', {'siem': 1})
        self.server.scenario['pending'] = False
        recovered = siem.reconcile(self.store, self.run, 'a', self.profile, result['connection_id'])
        self.assertTrue(recovered['consumer_stopped'])
        self.store.finish_task(self.run, 'a')

    def test_lost_submission_and_failed_cancel_keep_the_lease(self):
        self.server.scenario.update(lost_submission=True, pending=True, cancel_failure=True)
        result = self.execute()
        self.assertFalse(result['consumer_stopped'])
        self.assertNotIn(os.environ['METIS_TEST_TOKEN'], json.dumps(result))
        self.assertNotIn(os.environ['METIS_TEST_TOKEN'], json.dumps(self.store.report(self.run)))
        with self.assertRaises(ValueError):
            self.store.finish_task(self.run, 'a')

    def test_redirects_are_not_followed_and_environment_proxies_are_ignored(self):
        with patch.dict(os.environ, {'HTTP_PROXY': 'http://127.0.0.1:1', 'HTTPS_PROXY': 'http://127.0.0.1:1'}):
            self.assertTrue(self.execute()['complete'])
        self.server.scenario['redirect'] = True
        result = self.execute()
        self.assertFalse(result['complete'])
        self.assertFalse(any(r[1] == '/sink' for r in self.server.scenario['requests']))

    def test_tokens_in_returned_evidence_are_redacted(self):
        self.server.scenario['rows'][0]['host'] = os.environ['METIS_TEST_TOKEN']
        result = self.execute()
        self.assertNotIn(os.environ['METIS_TEST_TOKEN'], json.dumps(result))
        self.assertEqual(result['rows'][0]['host'], '[REDACTED]')
        self.server.scenario['rows'][0]['host'] = 'password=example-value'
        result = self.execute()
        self.assertTrue(result['complete'])
        self.assertNotIn('example-value', json.dumps(result))

    def test_splunk_session_key_authorization_is_explicit(self):
        self.profile['auth_scheme'] = 'Splunk'
        self.assertTrue(self.execute()['complete'])
        headers = self.server.scenario['requests'][0][4]
        self.assertEqual(headers['Authorization'], 'Splunk ' + os.environ['METIS_TEST_TOKEN'])
        self.assertNotIn(os.environ['METIS_TEST_TOKEN'], json.dumps(self.store.report(self.run)))

    def test_no_request_without_a_resource_lease(self):
        with self.assertRaises(PermissionError):
            siem.execute(self.store, self.run, 'b', self.profile, self.request)
        self.assertEqual(self.server.scenario['requests'], [])

    def test_reconcile_is_bound_to_the_original_task_and_profile(self):
        result = self.execute()
        with self.assertRaises(siem.SIEMError):
            siem.reconcile(self.store, self.run, 'b', self.profile, result['connection_id'])
        changed = dict(self.profile, resource='other')
        with self.assertRaises(siem.SIEMError):
            siem.reconcile(self.store, self.run, 'a', changed, result['connection_id'])

    def test_arbitrary_query_syntax_and_out_of_scope_fields_are_rejected(self):
        p = siem.validate_profile(self.profile)
        for key, value in [('search', 'arbitrary text'), ('script', 'arbitrary text')]:
            request = dict(self.request, **{key: value})
            with self.assertRaises(siem.SIEMError):
                siem.validate_request(p, request)
        for value in ('a|unexpected', 'a" unexpected', 'a`unexpected`', '*', '[subquery]'):
            request = copy.deepcopy(self.request)
            request['filters']['host'] = value
            with self.assertRaises(siem.SIEMError):
                siem.validate_request(p, request)
        for request in (dict(self.request, index='other'), dict(self.request, fields=['unapproved']),
                        dict(self.request, limit=10000), dict(self.request, end='2026-02-01T00:01:00Z')):
            with self.assertRaises(siem.SIEMError):
                siem.validate_request(p, request)

    def test_plain_http_is_only_enabled_for_literal_loopback_test_origins(self):
        for url in ('http://example.invalid', 'http://localhost', 'https://u:p@example.invalid',
                    'https://example.invalid/path', 'https://example.invalid?secret=1'):
            with self.assertRaises(siem.SIEMError):
                siem.validate_profile(dict(self.profile, base_url=url))
        with self.assertRaises(siem.SIEMError):
            siem.validate_profile(dict(self.profile, test_only_http=False))
        valid = siem.validate_profile(dict(self.profile, base_url='https://example.invalid'))
        self.assertEqual(siem.Transport(valid).context.verify_mode, __import__('ssl').CERT_REQUIRED)
        self.assertTrue(siem.Transport(valid).context.check_hostname)

    def test_elastic_bounded_body_and_local_field_projection(self):
        self.elastic()
        result = self.execute()
        self.assertTrue(result['complete'])
        self.assertEqual(result['rows'][0]['fields'], {'host.name': 'asset-7'})
        self.assertNotIn('private-data', json.dumps(result))
        sent = self.server.scenario['requests'][0]
        body = json.loads(sent[3])
        self.assertEqual(body['size'], 10)
        self.assertEqual(body['timeout'], '1s')
        self.assertEqual(sent[2]['allow_partial_search_results'], ['false'])
        self.assertNotIn('script', body)

    def test_elastic_partial_results_and_nonexact_totals_are_not_complete(self):
        self.elastic()
        base = {'timed_out': False, '_shards': {'total': 2, 'successful': 2, 'failed': 0},
                'hits': {'total': {'value': 0, 'relation': 'eq'}, 'hits': []}}
        for change in ({'timed_out': True}, {'_shards': {'total': 2, 'successful': 1, 'failed': 1}},
                       {'terminated_early': True}, {'hits': {'total': {'value': 10, 'relation': 'gte'}, 'hits': []}}):
            self.server.scenario['elastic_response'] = dict(base, **change)
            result = self.execute()
            self.assertFalse(result['complete'])
            self.assertTrue(result['consumer_stopped'])
        self.server.scenario['elastic_response'] = base
        self.assertTrue(self.execute()['complete'])
        self.server.scenario['elastic_response'] = dict(base, hits={
            'total': {'value': 0, 'relation': 'gte'},
            'hits': [{'_index': 'events', '_id': 'one', '_source': {'host': {'name': 'asset-7'}}}]})
        result = self.execute()
        self.assertFalse(result['complete'])
        self.assertTrue(result['consumer_stopped'])
        self.assertEqual(result['returned'], 1)

    def test_elastic_lost_error_response_does_not_claim_server_completion(self):
        self.elastic()
        self.server.scenario['elastic_error'] = True
        result = self.execute()
        self.assertFalse(result['consumer_stopped'])
        self.assertEqual(result['status'], 'indeterminate')
        self.assertNotIn(os.environ['METIS_TEST_TOKEN'], json.dumps(result))
        with self.assertRaises(ValueError):
            self.store.finish_task(self.run, 'a')

    def test_oversized_or_ambiguous_json_is_rejected(self):
        self.elastic()
        self.server.scenario['oversized'] = True
        self.assertIn('response-byte-limit', self.execute()['reasons'])
        for value in ('{"a":1,"a":2}', '{"n":NaN}', '{"n":1e9999}', '{"n":-1e9999}', '{"n":' + '9' * 513 + '}'):
            with self.assertRaises(siem.SIEMError):
                siem.parse_json(value)
        with self.assertRaises(siem.SIEMError):
            siem.bit(1.0)

    def test_elastic_inconsistent_completion_metadata_is_indeterminate(self):
        self.elastic()
        profile = siem.validate_profile(self.profile)
        request = siem.validate_request(profile, self.request)
        base = {'timed_out': False, '_shards': {'total': 1, 'successful': 1, 'failed': 0},
                'hits': {'total': {'value': 0, 'relation': 'eq'}, 'hits': []}}
        for changed in ({'_shards': {'total': 1, 'successful': 2, 'failed': 0}},
                        {'_shards': {'total': 1, 'successful': 1, 'failed': 0, 'skipped': 2}},
                        {'terminated_early': 'false'}, {'terminated_early': 0}):
            self.server.scenario['elastic_response'] = dict(base, **changed)
            rows, total, reasons, stopped = siem.elastic(siem.Transport(profile), profile, request)
            self.assertEqual(rows, [])
            self.assertIsNone(total)
            self.assertEqual(reasons, ['invalid-search-result'])
            self.assertFalse(stopped)


if __name__ == '__main__':
    unittest.main()
