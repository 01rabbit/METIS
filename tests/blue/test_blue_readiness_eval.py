"""Offline tests of the evaluation boundary, not model-quality claims."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from metis.blue.runtime import readiness_eval as evaluation


class ReadinessEvalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'skills/test').mkdir(parents=True)
        (self.root / 'examples').mkdir()
        self.reference = self.root / 'skills/test/SKILL.md'
        self.reference.write_text('Read the observed fields; missing evidence remains unknown.\n')
        self.expected = {'known': True, 'count': 1, 'value': 'SCORER_ONLY_97a4', 'ids': ['one', 'two']}
        self.cases = [{'id': 'one', 'question': 'Assess the supplied synthetic observations.',
                       'references': ['skills/test/SKILL.md', 'skills/test/SKILL.md'], 'expected': self.expected}]
        (self.root / 'examples/readiness-cases.json').write_text(json.dumps(self.cases))
        self.receipt = evaluation.bundle(root=self.root, out='.state/benchmarks/fresh.prompt.txt')
        self.answer = self.root / '.state/benchmarks/answer.json'

    def score(self, answer):
        self.answer.write_text(json.dumps(answer))
        return evaluation.score(root=self.root, answer=self.answer, bundle_meta=self.receipt['metadata'],
                                model='observed-test-label', provider='desktop')

    def test_bundle_deduplicates_references_and_excludes_scorer_values(self):
        prompt = Path(self.receipt['prompt']).read_text()
        self.assertNotIn('SCORER_ONLY_97a4', prompt)
        self.assertEqual(prompt.count('REFERENCE skills/test/SKILL.md\n'), 1)
        self.assertIn('"ids": "array[string]"', prompt)
        metadata = json.loads(Path(self.receipt['metadata']).read_text())
        self.assertEqual(len(metadata['references']), 1)
        self.assertEqual(metadata['field_count'], 4)
        self.assertEqual(metadata['prompt_sha256'], evaluation.digest(prompt.encode()))

    def test_v1_prompt_bytes_and_existing_bundle_scoring_remain_compatible(self):
        original = Path(self.receipt['prompt']).read_bytes()
        # Golden digest of the v1 prompt for this inert fixture (re-captured after the METIS rename).
        self.assertEqual(evaluation.digest(original), '3050194557a32478fe20cf4e4890d8df2d6dfb813120c59d6b67aa68996170b8')
        self.assertEqual(evaluation.PROTOCOL, 'blue-readiness-v1')
        for selection in ('v1', 'blue-readiness-v1'):
            generated, metadata = evaluation.build_payload(self.root, 'examples/readiness-cases.json', selection)
            self.assertEqual(generated, original)
            self.assertEqual(metadata['protocol'], 'blue-readiness-v1')
        # Creating a v2 bundle in another path must not relabel or invalidate an old v1 bundle.
        evaluation.bundle(root=self.root, out='.state/benchmarks/v2.prompt.txt', protocol='v2')
        result = self.score({'one': self.expected})
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['protocol'], 'blue-readiness-v1')

    def test_v2_only_appends_the_terminal_contract_without_answers_or_case_changes(self):
        old, old_metadata = evaluation.build_payload(self.root, 'examples/readiness-cases.json')
        new, metadata = evaluation.build_payload(self.root, 'examples/readiness-cases.json', 'v2')
        self.assertEqual(new, old + evaluation.V2_TERMINAL_CONTRACT.encode())
        self.assertNotIn(b'SCORER_ONLY_97a4', new)
        for field in ('cases_path', 'cases_sha256', 'references', 'answer_schemas', 'case_count', 'field_count'):
            self.assertEqual(metadata[field], old_metadata[field])
        self.assertEqual(metadata['protocol'], 'blue-readiness-v2')
        self.assertNotEqual(metadata['prompt_sha256'], old_metadata['prompt_sha256'])
        for phrase in ('final channel', 'starting with { and ending with }', 'No explanations, Markdown, or code fences',
                       'Do not call any tool', 'no-op, preflight, or placeholder', 'judgments only'):
            self.assertIn(phrase, new.decode().splitlines()[-1])

    def test_protocols_use_the_same_strict_scorer_without_extracting_json(self):
        valid = json.dumps({'one': self.expected})
        for protocol in ('v1', 'v2'):
            receipt = evaluation.bundle(root=self.root, out='.state/benchmarks/' + protocol + '.prompt.txt', protocol=protocol)
            for answer, status in ((valid, 'passed'), ('Here is the answer.\n' + valid, 'failed'),
                                   ('```json\n' + valid + '\n```', 'failed')):
                self.answer.write_text(answer)
                result = evaluation.score(root=self.root, answer=self.answer, bundle_meta=receipt['metadata'],
                                          model='fixture', provider='desktop')
                self.assertEqual(result['status'], status)
                self.assertEqual(result['protocol'], 'blue-readiness-' + protocol)

    def test_cli_protocol_and_alternate_cases_are_explicit(self):
        alternative = [dict(self.cases[0], id='different', question='Assess this independently supplied observation.',
                            expected={'decision': 'ALTERNATE_SCORER_ONLY_82'})]
        (self.root / 'examples/alternate.json').write_text(json.dumps(alternative))
        with patch.object(evaluation, 'ROOT', self.root), redirect_stdout(io.StringIO()):
            # Defaults bound at function definition are passed explicitly by this wrapper for the isolated root.
            original = evaluation.bundle
            def local_bundle(**kwargs):
                return original(root=self.root, **kwargs)
            with patch.object(evaluation, 'bundle', side_effect=local_bundle):
                code = evaluation.main(['bundle', '--protocol', 'v2', '--cases', 'examples/alternate.json',
                                        '--out', '.state/benchmarks/alternate.prompt.txt'])
        self.assertEqual(code, 0)
        prompt = (self.root / '.state/benchmarks/alternate.prompt.txt').read_text()
        self.assertIn('CASE different\n', prompt)
        self.assertNotIn('ALTERNATE_SCORER_ONLY_82', prompt)
        self.answer.write_text(json.dumps({'different': {'decision': 'ALTERNATE_SCORER_ONLY_82'}}))
        result = evaluation.score(root=self.root, answer=self.answer,
            bundle_meta='.state/benchmarks/alternate.meta.json', model='fixture', provider='desktop')
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['protocol'], 'blue-readiness-v2')

    def test_unknown_or_relabelled_protocol_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'unsupported-readiness-protocol'):
            evaluation.build_payload(self.root, 'examples/readiness-cases.json', 'v3')
        path = Path(self.receipt['metadata'])
        metadata = json.loads(path.read_text())
        metadata['protocol'] = 'blue-readiness-v3'
        path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, 'invalid-bundle-metadata'):
            self.score({'one': self.expected})
        metadata['protocol'] = 'blue-readiness-v2'
        path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, 'stale-or-modified-bundle'):
            self.score({'one': self.expected})

    def test_exact_answer_passes_and_unknown_usage_is_null(self):
        result = self.score({'one': self.expected})
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['fields_correct'], 4)
        self.assertEqual(result['usage']['source'], 'unavailable')
        self.assertTrue(all(result['usage'][key] is None for key in evaluation.USAGE_KEYS))

    def test_types_arrays_keys_and_missing_cases_are_strict(self):
        wrong = {'known': 1, 'count': True, 'value': self.expected['value'], 'ids': ['one', 2], 'extra': False}
        result = self.score({'one': wrong, 'extra_case': {}})
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['fields_correct'], 1)
        self.assertEqual(result['results'][0]['extra_fields'], ['extra'])
        self.assertEqual([field['type_matches'] for field in result['results'][0]['fields']], [False, False, True, False])
        self.assertEqual(result['extra_cases'], ['extra_case'])
        self.assertEqual(self.score({})['fields_correct'], 0)
        partial = dict(self.expected)
        del partial['count']
        self.assertEqual(self.score({'one': partial})['results'][0]['missing_fields'], ['count'])
        reordered = dict(self.expected, ids=['two', 'one'])
        self.assertEqual(self.score({'one': reordered})['status'], 'failed')

    def test_changed_reference_case_or_prompt_invalidates_the_bundle(self):
        original = self.reference.read_text()
        self.reference.write_text(original + 'New scope.\n')
        with self.assertRaisesRegex(ValueError, 'stale-or-modified'):
            self.score({'one': self.expected})
        self.reference.write_text(original)
        path = self.root / 'examples/readiness-cases.json'
        original_cases = path.read_text()
        self.cases[0]['expected']['count'] = 2
        path.write_text(json.dumps(self.cases))
        with self.assertRaisesRegex(ValueError, 'stale-or-modified'):
            self.score({'one': self.expected})
        path.write_text(original_cases)
        Path(self.receipt['prompt']).write_text('Different text was pasted.')
        with self.assertRaisesRegex(ValueError, 'stale-or-modified'):
            self.score({'one': self.expected})

    def test_duplicate_json_and_nonprivate_or_symlink_outputs_are_rejected(self):
        self.answer.write_text('{"one":{},"one":{}}')
        result = evaluation.score(root=self.root, answer=self.answer, bundle_meta=self.receipt['metadata'],
                                  model='test', provider='ollama')
        self.assertEqual(result['status'], 'failed')
        self.assertIn('invalid-answer-json', result['errors'])
        with self.assertRaises(ValueError):
            evaluation.bundle(root=self.root, out='examples/leak.prompt.txt')
        (self.root / '.state/benchmarks/alias').symlink_to(self.root / 'examples', target_is_directory=True)
        with self.assertRaises(ValueError):
            evaluation.bundle(root=self.root, out='.state/benchmarks/alias/leak.prompt.txt')
        with self.assertRaises(ValueError):
            evaluation.usage_record({'input_tokens': True})
        self.assertEqual(evaluation.usage_record({'input_tokens': 0})['input_tokens'], 0)

    def engine(self, mode='success', usage=True, installed=True):
        outer = self
        class FakeClient:
            url = 'http://127.0.0.1:11434'
            calls = 0
            def __init__(self, url, timeout, **options):
                self.options = options
                outer.assertEqual(options['num_ctx'], 65536)
            def inventory(self):
                return {'version': {'version': 'fixture'}, 'models': [{'name': 'fixture:model'}] if installed else []}
            def call(self, model, text, store, run, task):
                FakeClient.calls += 1
                outer.assertNotIn('SCORER_ONLY_97a4', text)
                guard = outer.root / ('.state/benchmarks/ollama-' + evaluation.digest(self.url.encode())[:16] + '.uncertain.json')
                outer.assertTrue(guard.exists(), 'occupancy marker must precede inference')
                if mode == 'timeout':
                    raise RuntimeError('Completion unknown')
                if mode == 'interrupted':
                    raise KeyboardInterrupt()
                answer = json.dumps({'one': outer.expected})
                metrics = {'model': model, 'done': True, 'done_reason': 'length' if mode == 'length' else 'stop'}
                if usage:
                    metrics.update(prompt_eval_count=200, eval_count=40)
                store.message(run, task, model, 'owner', 'benchmark-answer', answer)
                store.message(run, task, model, 'owner', 'provider-metrics', json.dumps(metrics))
                if mode == 'length':
                    raise RuntimeError('Generation reached limit')
                return {'text': answer, 'metrics': metrics}
        return FakeClient

    def run_fixture(self, factory, name='run'):
        return evaluation.run_ollama(root=self.root, bundle_meta=self.receipt['metadata'],
            model='fixture:model', out='.state/benchmarks/' + name + '.json', client_factory=factory)

    def test_ollama_one_inference_uses_frozen_prompt_and_measured_counts(self):
        factory = self.engine()
        result = self.run_fixture(factory)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(factory.calls, 1)
        self.assertEqual(result['usage']['total_tokens'], 240)
        self.assertIsNone(result['usage']['cached_input_tokens'])
        self.assertTrue(result['model_identity_verified'])
        receipt = evaluation.parse_json((self.root / result['provider_receipt']).read_bytes())
        self.assertEqual(receipt['num_ctx'], 65536)
        self.assertEqual(receipt['answer_sha256'], result['answer_sha256'])
        with self.assertRaisesRegex(ValueError, 'already-exists'):
            self.run_fixture(factory)
        self.assertEqual(factory.calls, 1)
        result = self.run_fixture(self.engine(usage=False), 'unknown-usage')
        self.assertTrue(all(result['usage'][key] is None for key in evaluation.USAGE_KEYS))

    def test_ollama_length_uninstalled_and_stale_never_pass(self):
        result = self.run_fixture(self.engine(mode='length'), 'length')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['reason'], 'generation-token-limit')
        self.assertEqual(result['usage']['total_tokens'], 240)
        factory = self.engine(installed=False)
        self.assertEqual(self.run_fixture(factory, 'uninstalled')['status'], 'failed')
        self.assertEqual(factory.calls, 0)
        self.reference.write_text('Changed guidance')
        with self.assertRaisesRegex(ValueError, 'stale-or-modified'):
            self.run_fixture(factory, 'stale')
        self.assertEqual(factory.calls, 0)

    def test_unknown_completion_prevents_any_subsequent_inference(self):
        factory = self.engine(mode='timeout')
        result = self.run_fixture(factory)
        self.assertTrue(result['server_completion_unknown'])
        self.assertEqual(factory.calls, 1)
        from metis.blue.runtime.skill_eval import inference_lock
        with self.assertRaisesRegex(RuntimeError, 'Reconcile'):
            with inference_lock(self.root / '.state/benchmarks', factory.url):
                self.fail('Shared inference lock must honor the uncertain marker')
        with self.assertRaisesRegex(RuntimeError, 'Reconcile'):
            self.run_fixture(factory, 'retry')
        self.assertEqual(factory.calls, 1)

    def test_process_interruption_leaves_persistent_occupancy_marker(self):
        factory = self.engine(mode='interrupted')
        with self.assertRaises(KeyboardInterrupt):
            self.run_fixture(factory)
        with self.assertRaisesRegex(RuntimeError, 'Reconcile'):
            self.run_fixture(factory, 'next')
        self.assertEqual(factory.calls, 1)

    def test_busy_inference_lock_rejects_without_a_provider_call(self):
        from metis.blue.runtime.skill_eval import inference_lock
        factory = self.engine()
        with inference_lock(self.root / '.state/benchmarks', factory.url):
            with self.assertRaises(BlockingIOError):
                self.run_fixture(factory)
        self.assertEqual(factory.calls, 0)

    def test_shared_lock_does_not_follow_links_or_truncate_existing_files(self):
        from metis.blue.runtime.skill_eval import inference_lock
        directory = self.root / '.state/benchmarks'
        key = 'fixture-lock'
        lock = directory / ('ollama-' + evaluation.digest(key.encode())[:16] + '.lock')
        target = directory / 'preserve.txt'
        target.write_text('unchanged')
        lock.symlink_to(target)
        with self.assertRaises(OSError), inference_lock(directory, key):
            self.fail('symlink lock was followed')
        self.assertEqual(target.read_text(), 'unchanged')
        lock.unlink()
        lock.write_text('existing lock metadata')
        with inference_lock(directory, key):
            pass
        self.assertEqual(lock.read_text(), 'existing lock metadata')

    def test_different_endpoints_cannot_share_an_output_reservation(self):
        first, second = self.engine(), self.engine()
        second.url = 'http://127.0.0.2:11434'
        original = first.call
        outer = self
        def during_call(client, *args):
            with outer.assertRaises(FileExistsError):
                outer.run_fixture(second)
            return original(client, *args)
        first.call = during_call
        result = self.run_fixture(first)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(first.calls, 1)
        self.assertEqual(second.calls, 0)
        path = self.root / '.state/benchmarks/preserve.json'
        evaluation.write_private(self.root, path, b'first', replace=False)
        with self.assertRaises(FileExistsError):
            evaluation.write_private(self.root, path, b'second', replace=False)
        self.assertEqual(path.read_bytes(), b'first')

    def test_case_change_between_validation_and_scoring_is_rejected(self):
        original = evaluation.read_cases
        reads = 0
        def changing_cases(root, relative):
            nonlocal reads
            reads += 1
            if reads == 2:
                path = root / relative
                cases = json.loads(path.read_text())
                cases[0]['expected']['count'] = 9
                path.write_text(json.dumps(cases))
            return original(root, relative)
        with patch.object(evaluation, 'read_cases', side_effect=changing_cases):
            with self.assertRaisesRegex(ValueError, 'stale-or-modified'):
                self.score({'one': self.expected})

    def test_rebundling_during_inference_cannot_relabel_the_measurement(self):
        factory = self.engine()
        original = factory.call
        before = json.loads(Path(self.receipt['metadata']).read_text())
        def changing_bundle(client, *args):
            self.reference.write_text(self.reference.read_text() + 'Additional guidance.\n')
            evaluation.bundle(root=self.root, out='.state/benchmarks/fresh.prompt.txt')
            return original(client, *args)
        factory.call = changing_bundle
        result = self.run_fixture(factory)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['prompt_sha256'], before['prompt_sha256'])
        receipt = json.loads((self.root / result['provider_receipt']).read_text())
        self.assertEqual(receipt['prompt_sha256'], result['prompt_sha256'])
        self.assertEqual(factory.calls, 1)

    def test_score_reports_the_metadata_snapshot_it_actually_validated(self):
        original = evaluation.read_cases
        reads = 0
        before = evaluation.digest(Path(self.receipt['metadata']).read_bytes())
        def changing_metadata(root, relative):
            nonlocal reads
            reads += 1
            if reads == 2:
                Path(self.receipt['metadata']).write_text('{}')
            return original(root, relative)
        with patch.object(evaluation, 'read_cases', side_effect=changing_metadata):
            result = self.score({'one': self.expected})
        self.assertEqual(result['bundle_sha256'], before)


if __name__ == '__main__':
    unittest.main()
