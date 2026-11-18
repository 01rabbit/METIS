import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from metis.blue.runtime import knowledge_intake as intake


class KnowledgeIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "metis"
        self.source = Path(self.tmp.name).resolve() / "source"
        self.root.mkdir(); self.source.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.source, check=True)
        self.original = self.source / "original.md"
        self.original.write_text("Source-only expression " + "a distinctive original sentence about observation and interpretation. " * 6)
        subprocess.run(["git", "add", "."], cwd=self.source, check=True)
        (self.root / "docs").mkdir()
        self.manifest = {"entries": [], "target_digests": {}}
        (self.root / "docs/migration.json").write_text(json.dumps(self.manifest))
        self.snapshot = intake.inventory(self.source)[0]
        self.draft = {"policy": intake.VERSION, "changes": [{
            "target": "skills/example/references/new.md",
            "text": "# Independently composed note\n\nCount observations only after defining the unit and collection interval.\n",
            "sources": [{k: self.snapshot["files"][0][k] for k in ("path_sha256", "content_sha256")}],
        }]}
        self.pattern = "retired-identity"

    def review(self, draft=None):
        return intake.check_draft(self.root, self.source, draft or self.draft, self.pattern)

    def attest(self, review):
        return {"review_sha256": intake.sha(intake.encoded(review)), "reviewer": "test reviewer",
                "independent_expression": True, "facts_and_methods_only": True,
                "no_case_or_secret": True, "no_source_code_or_media": True,
                "scope_and_accuracy_checked": True}

    def test_snapshot_and_delta_do_not_contain_source_text_or_paths(self):
        serialized = json.dumps(self.snapshot)
        self.assertNotIn("original.md", serialized)
        self.assertNotIn("Source-only", serialized)
        self.original.write_text("Changed source")
        delta = intake.compare(intake.inventory(self.source)[0], self.snapshot)
        self.assertEqual(len(delta["changed"]), 1)

    def test_baseline_cannot_smuggle_raw_paths_into_delta(self):
        baseline = copy.deepcopy(self.snapshot)
        baseline["files"][0]["path_sha256"] = "source-private-name.md"
        payload = {k: v for k, v in baseline.items() if k != "snapshot_sha256"}
        baseline["snapshot_sha256"] = intake.sha(intake.encoded(payload))
        with self.assertRaises(ValueError):
            intake.compare(self.snapshot, baseline)

    def test_verbatim_and_format_changed_copy_are_blocked(self):
        for text in (self.original.read_text(), self.original.read_text().upper().replace(" ", "\n")):
            draft = copy.deepcopy(self.draft)
            draft["changes"][0]["text"] = text
            self.assertIn("0:source-expression-overlap", self.review(draft)["errors"])

    def test_fenced_code_media_and_opaque_encoding_are_blocked(self):
        for text in ("~~~python\nprint(1)\n~~~", "![copied](picture.png)", "A" * 160):
            draft = copy.deepcopy(self.draft); draft["changes"][0]["text"] = text
            self.assertTrue(self.review(draft)["errors"])

    def test_identifiers_and_missing_policy_are_blocked(self):
        draft = copy.deepcopy(self.draft); draft["changes"][0]["text"] = "A retired-identity"
        self.assertIn("0:prohibited-identity", self.review(draft)["errors"])
        self.assertIn("identifier-policy-required",
                      intake.check_draft(self.root, self.source, self.draft, None)["errors"])
        draft["changes"][0]["target"] = "skills/retired-identity/new.md"
        self.assertNotIn("retired-identity", json.dumps(self.review(draft)))

    def test_path_escape_and_symlinks_are_blocked(self):
        for target in ("../escape.md", "/tmp/escape.md", "metis/tool.py", "skills/example//new.md"):
            draft = copy.deepcopy(self.draft); draft["changes"][0]["target"] = target
            self.assertIn("0:invalid-change", self.review(draft)["errors"])
        (self.root / "skills").symlink_to(self.source, target_is_directory=True)
        self.assertIn("0:invalid-change", self.review()["errors"])

    def test_stale_source_or_target_invalidates_review(self):
        review = self.review()
        self.original.write_text("A newer source revision")
        with self.assertRaises(ValueError):
            intake.apply_draft(self.root, self.source, self.draft, review, self.attest(review), self.pattern)
        self.assertFalse((self.root / self.draft["changes"][0]["target"]).exists())

    def test_no_application_without_explicit_review(self):
        review = self.review()
        self.assertFalse(review["errors"])
        with self.assertRaises(ValueError):
            intake.apply_draft(self.root, self.source, self.draft, review, {}, self.pattern)

    def test_success_updates_digest_and_writes_only_independent_text(self):
        review = self.review()
        receipt = intake.apply_draft(self.root, self.source, self.draft, review, self.attest(review), self.pattern)
        path = self.root / self.draft["changes"][0]["target"]
        self.assertEqual(path.read_text(), self.draft["changes"][0]["text"])
        ledger = (self.root / "docs/intake-ledger.json").read_text()
        self.assertNotIn("Source-only", ledger)
        self.assertNotIn("original.md", ledger)
        manifest = json.loads((self.root / "docs/migration.json").read_text())
        self.assertEqual(manifest["target_digests"][str(path.relative_to(self.root))],
                         intake.sha(path.read_bytes()))
        self.assertEqual(receipt["draft_sha256"], review["draft_sha256"])

    def test_review_cannot_be_reused_for_changed_draft(self):
        review = self.review()
        draft = copy.deepcopy(self.draft); draft["changes"][0]["text"] += "Extra material."
        with self.assertRaises(ValueError):
            intake.apply_draft(self.root, self.source, draft, review, self.attest(review), self.pattern)

    def test_concurrent_target_edit_invalidates_review(self):
        review = self.review()
        path = self.root / self.draft["changes"][0]["target"]
        path.parent.mkdir(parents=True)
        path.write_text("Another editor's work")
        with self.assertRaises(ValueError):
            intake.apply_draft(self.root, self.source, self.draft, review, self.attest(review), self.pattern)
        self.assertEqual(path.read_text(), "Another editor's work")

    def test_extra_fields_and_duplicate_keys_are_rejected(self):
        draft = copy.deepcopy(self.draft)
        draft["raw_source"] = "Content must not be smuggled through unused fields"
        self.assertIn("unexpected-draft-fields", self.review(draft)["errors"])
        with self.assertRaises(ValueError):
            json.loads('{"policy":1,"policy":2}', object_pairs_hook=intake.strict_object)

    def test_source_symlink_is_not_followed(self):
        (self.source / "link.md").symlink_to(self.root / "docs/migration.json")
        subprocess.run(["git", "add", "link.md"], cwd=self.source, check=True)
        with self.assertRaises(ValueError):
            intake.inventory(self.source)

    def test_existing_library_requires_review_without_exporting_matches(self):
        target = self.root / "skills/example/SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text(self.original.read_text())
        report = intake.audit_library(self.root, self.source)
        self.assertEqual(report["summary"]["identical"], 1)
        self.assertEqual(report["summary"]["requires_expression_review"], 1)
        self.assertTrue(report["errors"])
        self.assertNotIn("Source-only", json.dumps(report))
        self.assertNotIn("original.md", json.dumps(report))
        target.write_text(self.draft["changes"][0]["text"])
        self.assertFalse(intake.audit_library(self.root, self.source)["errors"])
        # Existing rules are inventoried too, even though new intake is prose-only.
        rule = self.root / "detections/example.yml"
        rule.parent.mkdir()
        rule.write_text(self.original.read_text())
        self.assertEqual(intake.audit_library(self.root, self.source)["summary"]["requires_expression_review"], 1)

    def test_root_overlap_is_rejected_before_any_write(self):
        for root, source in ((self.source, self.source),
                             (self.source, self.source / "nested"),
                             (self.source / "nested", self.source)):
            (self.source / "nested").mkdir(exist_ok=True)
            with self.subTest(root=root, source=source), self.assertRaises(ValueError):
                intake.apply_draft(root, source, self.draft, {}, {}, self.pattern)
        self.assertFalse((self.source / ".state").exists())

    def test_manifest_change_invalidates_review(self):
        review = self.review()
        manifest = self.root / "docs/migration.json"
        modified = dict(self.manifest, unrelated_change=True)
        manifest.write_text(json.dumps(modified))
        with self.assertRaises(ValueError):
            intake.apply_draft(self.root, self.source, self.draft, review, self.attest(review), self.pattern)
        self.assertEqual(json.loads(manifest.read_text()), modified)
        self.assertFalse((self.root / self.draft["changes"][0]["target"]).exists())

    def test_internal_symlinks_cannot_reach_source(self):
        (self.root / ".state").symlink_to(self.source, target_is_directory=True)
        review = self.review()
        with self.assertRaises(ValueError):
            intake.apply_draft(self.root, self.source, self.draft, review, self.attest(review), self.pattern)
        self.assertFalse((self.source / "intake").exists())
        (self.root / ".state").unlink()
        manifest = self.root / "docs/migration.json"
        manifest.unlink()
        manifest.symlink_to(self.original)
        with self.assertRaises(ValueError):
            self.review()

    def test_output_boundary_and_input_collisions(self):
        private = self.root / intake.PRIVATE
        private.mkdir(parents=True)
        draft = private / "draft.json"
        draft.write_text(json.dumps(self.draft))
        for out in (draft, self.original, private / "transaction/receipt.json", private / "apply.lock"):
            with self.subTest(out=out), self.assertRaises(ValueError):
                intake.private_report_path(self.root, out, (draft,))
        (private / "outside").symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):
            intake.private_report_path(self.root, private / "outside/report.json")

    def test_cli_collision_is_blocked_without_overwriting_draft(self):
        private = self.root / intake.PRIVATE
        private.mkdir(parents=True)
        draft = private / "draft.json"
        original = json.dumps(self.draft).encode()
        draft.write_bytes(original)
        result = subprocess.run([sys.executable, "-m", "metis.blue.runtime.knowledge_intake", "check",
                                 "--root", str(self.root), "--source", str(self.source),
                                 "--draft", str(draft), "--out", str(draft)],
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(draft.read_bytes(), original)
        self.assertNotIn(str(self.source).encode(), result.stdout + result.stderr)

    def test_extra_attestation_fields_are_rejected(self):
        review = self.review()
        attestation = self.attest(review)
        attestation["original_passage"] = "Not part of the review contract"
        self.assertFalse(intake.verify_attestation(review, attestation))

    def test_structurally_invalid_inputs_fail_closed(self):
        for draft in (None, [], "text", {"policy": intake.VERSION, "changes": None}):
            with self.subTest(draft=draft), self.assertRaises(ValueError):
                intake.check_draft(self.root, self.source, draft, self.pattern)
        for change in (None, [], "text", 3):
            draft = {"policy": intake.VERSION, "changes": [change]}
            self.assertEqual(self.review(draft)["errors"], ["0:invalid-change"])
        self.assertFalse(intake.verify_attestation({}, []))

    def test_nonfenced_media_and_indented_code_are_blocked(self):
        for text in ("<video src='media.mp4'></video>", "<svg></svg>",
                     "    copied_code()", "\tindented_code()"):
            draft = copy.deepcopy(self.draft)
            draft["changes"][0]["text"] = text
            self.assertIn("0:code-or-media-not-accepted", self.review(draft)["errors"])

    def test_native_initializer_identifiers_survive_intake_unchanged(self):
        draft = copy.deepcopy(self.draft)
        text = "Read the DEX method names `<clinit>` and `<init>` as static metadata.\n"
        draft["changes"][0]["text"] = text
        review = self.review(draft)
        self.assertEqual(review["errors"], [])
        intake.apply_draft(self.root, self.source, draft, review,
                           self.attest(review), self.pattern)
        self.assertEqual((self.root / draft["changes"][0]["target"]).read_text(), text)

    def test_complete_registry_literal_requires_specific_factual_review(self):
        key = r"HKCU\Software\ExampleVendor\ExampleProduct\LongNamedComponentForEvidenceReview\Settings"
        self.original.write_text(key)
        draft = copy.deepcopy(self.draft)
        draft["changes"][0]["sources"] = [{k: intake.inventory(self.source)[0]["files"][0][k]
                                           for k in ("path_sha256", "content_sha256")}]
        draft["changes"][0]["text"] = "Inspect the acquired key `" + key + "`; validate the value type.\n"
        review = self.review(draft)
        self.assertEqual(review["errors"], [])
        self.assertEqual(review["native_registry_review"][0]["literal_sha256"], [intake.sha(key.encode())])
        attestation = self.attest(review)
        with self.assertRaises(ValueError):
            intake.apply_draft(self.root, self.source, draft, review, attestation, self.pattern)
        attestation["native_registry_identifiers_are_factual"] = True
        intake.apply_draft(self.root, self.source, draft, review, attestation, self.pattern)
        self.assertEqual((self.root / draft["changes"][0]["target"]).read_text(), draft["changes"][0]["text"])
        # A raw audit must retain the match for accountable adjudication.
        audit = intake.audit_library(self.root, self.source)
        self.assertTrue(audit["files"][0]["native_registry_only"])
        self.assertEqual(audit["summary"]["requires_expression_review"], 1)

    def test_registry_fact_review_never_excuses_adjacent_prose_or_identity(self):
        key = r"HKCU\Software\ExampleVendor\ExampleProduct\LongNamedComponentForEvidenceReview\Settings"
        prose = "A distinctive explanatory passage about observed evidence and interpretation boundaries. " * 3
        self.original.write_text(prose + key + prose)
        snapshot = intake.inventory(self.source)[0]
        for text, error in ((prose + "`" + key + "`", "source-expression-overlap"),
                            ("`" + key + "` retired-identity", "prohibited-identity"),
                            ("`" + key + "` <script>value</script>", "code-or-media-not-accepted"),
                            ("```" + key + "```", "code-or-media-not-accepted")):
            draft = copy.deepcopy(self.draft)
            draft["changes"][0]["sources"] = [{k: snapshot["files"][0][k] for k in ("path_sha256", "content_sha256")}]
            draft["changes"][0]["text"] = text
            self.assertIn("0:" + error, self.review(draft)["errors"])

    def test_registry_match_must_not_cross_literal_boundary(self):
        key = r"HKCU\Software\Example\Settings"
        text = "An independently required surrounding passage before `" + key + "` and after."
        plain = intake.normalize(text)
        grams = {intake.sha(plain[i:i + intake.WIDTH].encode())
                 for i in range(len(plain) - intake.WIDTH + 1)}
        result = intake.overlap_review(text, grams)
        self.assertTrue(result["non_registry_overlap"])
        self.assertEqual(result["native_registry_sha256"], [])

    def test_initializer_exception_does_not_admit_html_or_media(self):
        for text in ("`<script>`", "`<init src='media'>`", "`<clinit>` <svg></svg>",
                     "```\n<clinit>\n```", "```<clinit>```", r"\`<clinit>`",
                     "`<clinit>` ![image](media.png)"):
            with self.subTest(text=text):
                draft = copy.deepcopy(self.draft)
                draft["changes"][0]["text"] = text
                self.assertIn("0:code-or-media-not-accepted", self.review(draft)["errors"])

    def test_source_change_after_file_read_is_detected(self):
        actual = intake.safe_read
        changed = False
        def mutate(path, limit):
            nonlocal changed
            raw = actual(path, limit)
            if path == self.original and not changed:
                path.write_text("Changed after this file was read")
                changed = True
            return raw
        with mock.patch.object(intake, "safe_read", side_effect=mutate), self.assertRaises(ValueError):
            intake.inventory(self.source)

    def test_another_apply_holds_the_exclusive_lock(self):
        review = self.review()
        with intake.intake_lock(self.root), self.assertRaises(BlockingIOError):
            intake.apply_draft(self.root, self.source, self.draft, review, self.attest(review), self.pattern)
        self.assertFalse((self.root / intake.TRANSACTION).exists())

    def transaction_fixture(self):
        draft = copy.deepcopy(self.draft)
        second = copy.deepcopy(draft["changes"][0])
        second["target"] = "playbooks/second.md"
        second["text"] = "# Separate review\n\nUse the collection boundaries when deciding what remains unknown.\n"
        draft["changes"].append(second)
        for index, change in enumerate(draft["changes"]):
            path = self.root / change["target"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"Existing destination document {index}\n")
        names = [c["target"] for c in draft["changes"]] + list(intake.INTERNAL_FILES)
        originals = {name: intake.optional_bytes(self.root / name) for name in names}
        return draft, originals

    def assert_originals(self, originals):
        for name, raw in originals.items():
            self.assertEqual(intake.optional_bytes(self.root / name), raw, name)

    def test_partial_write_failure_restores_every_destination(self):
        draft, originals = self.transaction_fixture()
        review = self.review(draft)
        actual = intake.atomic_bytes
        failed = False
        def fail_once(path, *args, **kwargs):
            nonlocal failed
            if path == self.root / intake.INTERNAL_FILES[0] and not failed:
                failed = True
                raise OSError("synthetic disk failure")
            return actual(path, *args, **kwargs)
        with mock.patch.object(intake, "atomic_bytes", side_effect=fail_once), self.assertRaises(OSError):
            intake.apply_draft(self.root, self.source, draft, review, self.attest(review), self.pattern)
        self.assert_originals(originals)
        self.assertFalse((self.root / intake.TRANSACTION).exists())

    def test_interruption_at_each_destination_boundary_is_recoverable(self):
        draft, originals = self.transaction_fixture()
        actual = intake.atomic_bytes
        for stop_after in range(1, len(originals) + 1):
            count = 0
            review = self.review(draft)
            def interrupt(path, *args, **kwargs):
                nonlocal count
                result = actual(path, *args, **kwargs)
                if str(path.relative_to(self.root)) in originals:
                    count += 1
                    if count == stop_after:
                        raise KeyboardInterrupt()
                return result
            with self.subTest(stop_after=stop_after):
                with mock.patch.object(intake, "atomic_bytes", side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
                    intake.apply_draft(self.root, self.source, draft, review, self.attest(review), self.pattern)
                with self.assertRaises(ValueError):
                    intake.apply_draft(self.root, self.source, draft, review, self.attest(review), self.pattern)
                self.assertEqual(intake.recover(self.root, self.source)["status"], "rolled-back")
                self.assert_originals(originals)
                self.assertEqual(intake.recover(self.root, self.source)["restored"], 0)

    def test_recovery_never_overwrites_a_later_editor(self):
        draft, originals = self.transaction_fixture()
        review = self.review(draft)
        actual = intake.atomic_bytes
        first = self.root / draft["changes"][0]["target"]
        def interrupt(path, *args, **kwargs):
            result = actual(path, *args, **kwargs)
            if path == first:
                raise KeyboardInterrupt()
            return result
        with mock.patch.object(intake, "atomic_bytes", side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
            intake.apply_draft(self.root, self.source, draft, review, self.attest(review), self.pattern)
        first.write_text("A later editor's change")
        with self.assertRaises(ValueError):
            intake.recover(self.root, self.source)
        self.assertEqual(first.read_text(), "A later editor's change")
        self.assertTrue((self.root / intake.TRANSACTION / "journal.json").exists())
        # An operator resolves the conflicting destination before retrying recovery.
        first.write_bytes(originals[str(first.relative_to(self.root))])
        intake.recover(self.root, self.source)
        self.assert_originals(originals)

    def test_invalid_or_escaping_journal_is_never_applied(self):
        draft, _originals = self.transaction_fixture()
        review = self.review(draft)
        with mock.patch.object(intake, "cleanup_transaction", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            intake.apply_draft(self.root, self.source, draft, review, self.attest(review), self.pattern)
        path = self.root / intake.TRANSACTION / "journal.json"
        journal = json.loads(path.read_text())
        journal["files"][0]["target"] = "../outside.md"
        path.write_text(json.dumps(journal))
        with self.assertRaises(ValueError):
            intake.recover(self.root, self.source)
        self.assertFalse((self.root.parent / "outside.md").exists())

    def test_committed_cleanup_does_not_undo_successful_application(self):
        review = self.review()
        with mock.patch.object(intake, "cleanup_transaction", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            intake.apply_draft(self.root, self.source, self.draft, review, self.attest(review), self.pattern)
        self.assertEqual(intake.recover(self.root, self.source)["status"], "committed-cleanup")
        path = self.root / self.draft["changes"][0]["target"]
        self.assertEqual(path.read_text(), self.draft["changes"][0]["text"])
        ledger = json.loads((self.root / intake.INTERNAL_FILES[1]).read_text())
        self.assertEqual(len(ledger["entries"]), 1)

    def test_incomplete_preparation_is_discarded_without_destination_changes(self):
        location = self.root / intake.TRANSACTION
        location.mkdir(parents=True)
        (location / ".intake-interrupted").write_text("Incomplete private preparation")
        self.assertEqual(intake.recover(self.root, self.source)["status"], "preparation-discarded")
        self.assertFalse(location.exists())

    def test_source_change_during_apply_rolls_back_destinations(self):
        draft, originals = self.transaction_fixture()
        review = self.review(draft)
        actual = intake.atomic_bytes
        first = self.root / draft["changes"][0]["target"]
        def mutate(path, *args, **kwargs):
            result = actual(path, *args, **kwargs)
            if path == first:
                self.original.write_text("A concurrent source update")
            return result
        with mock.patch.object(intake, "atomic_bytes", side_effect=mutate), self.assertRaises(ValueError):
            intake.apply_draft(self.root, self.source, draft, review, self.attest(review), self.pattern)
        self.assert_originals(originals)
        self.assertFalse((self.root / intake.TRANSACTION).exists())

    def test_duplicate_application_is_rejected_before_writing(self):
        review = self.review()
        intake.apply_draft(self.root, self.source, self.draft, review, self.attest(review), self.pattern)
        review = self.review()
        ledger = (self.root / intake.INTERNAL_FILES[1]).read_bytes()
        with self.assertRaises(ValueError):
            intake.apply_draft(self.root, self.source, self.draft, review, self.attest(review), self.pattern)
        self.assertEqual((self.root / intake.INTERNAL_FILES[1]).read_bytes(), ledger)
        self.assertFalse((self.root / intake.TRANSACTION).exists())

    def test_actual_process_termination_can_be_recovered(self):
        draft, originals = self.transaction_fixture()
        private = self.root / intake.PRIVATE
        private.mkdir(parents=True)
        (private / "draft.json").write_text(json.dumps(draft))
        script = '''
import json, os, sys
from pathlib import Path
from metis.blue.runtime import knowledge_intake as k
root, source = Path(sys.argv[1]), Path(sys.argv[2])
draft = json.loads((root / k.PRIVATE / "draft.json").read_text())
review = k.check_draft(root, source, draft, "retired-identity")
attestation = {"review_sha256": k.sha(k.encoded(review)), "reviewer": "process test",
               "independent_expression": True, "facts_and_methods_only": True,
               "no_case_or_secret": True, "no_source_code_or_media": True,
               "scope_and_accuracy_checked": True}
original = k.atomic_bytes
def stop(path, *args, **kwargs):
    result = original(path, *args, **kwargs)
    if path == root / draft["changes"][0]["target"]:
        os._exit(73)
    return result
k.atomic_bytes = stop
k.apply_draft(root, source, draft, review, attestation, "retired-identity")
'''
        completed = subprocess.run([sys.executable, "-c", script, str(self.root), str(self.source)],
                                   capture_output=True, timeout=20, check=False)
        self.assertEqual(completed.returncode, 73, completed.stderr.decode())
        self.assertTrue((private / "transaction/journal.json").exists())
        self.assertEqual(intake.recover(self.root, self.source)["status"], "rolled-back")
        self.assert_originals(originals)


if __name__ == "__main__":
    unittest.main()
