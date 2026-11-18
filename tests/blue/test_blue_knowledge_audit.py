"""Integrity checks must fail closed when sources, targets or hidden Git objects drift."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "audit_knowledge", Path(__file__).resolve().parents[2] / "blue/scripts/audit_knowledge.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class KnowledgeAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "output"
        self.source = Path(self.temp.name) / "source"
        self.root.mkdir()
        self.source.mkdir()
        self.git(self.source, "init", "-q")
        self.source_file = self.source / "knowledge.md"
        self.source_file.write_text("Generic defensive lesson\n")
        self.git(self.source, "add", "knowledge.md")
        self.target = self.root / "skills/sample/SKILL.md"
        self.target.parent.mkdir(parents=True)
        self.target.write_text("Adapted defensive lesson\n")
        self.target_name = str(self.target.relative_to(self.root))
        (self.root / "docs").mkdir()
        self.entry = {
            "source_id": "knowledge-001", "kind": "skill",
            "source_sha256": audit.digest(self.source_file.read_bytes()),
            "target": self.target_name, "target_sha256": audit.digest(self.target.read_bytes()),
        }
        self.manifest = {
            "source_manifests": 1, "entries": [self.entry],
            "target_digests": {self.target_name: self.entry["target_sha256"]},
        }
        self.coverage = {"source_file_count": 1, "files": [{
            "path_sha256": audit.digest(b"knowledge.md"),
            "content_sha256": self.entry["source_sha256"],
            "disposition": "adapted-knowledge", "source_id": "knowledge-001",
        }]}
        self.save()

    @staticmethod
    def git(root, *args, input=None):
        return subprocess.check_output(["git", *args], cwd=root, input=input)

    def save(self):
        (self.root / "docs/migration.json").write_text(json.dumps(self.manifest))
        (self.root / "docs/knowledge-coverage.json").write_text(json.dumps(self.coverage))

    def test_verified_sources_and_targets_pass(self):
        self.assertEqual(audit.verify_coverage(self.root, self.source), [])

    def test_target_changes_and_deletions_are_detected(self):
        self.target.write_text("Unreviewed change")
        self.assertTrue(any("digest changed" in x for x in audit.verify_coverage(self.root)))
        self.target.unlink()
        self.assertTrue(any("Missing or unsafe" in x for x in audit.verify_coverage(self.root)))

    def test_new_or_modified_source_requires_review(self):
        self.source_file.write_text("Changed knowledge")
        extra = self.source / "new.md"
        extra.write_text("New lesson")
        self.git(self.source, "add", "new.md")
        errors = audit.verify_coverage(self.root, self.source)
        self.assertTrue(any("added=1, missing=0, changed=1" in x for x in errors))

    def test_orphaned_knowledge_mapping_is_rejected(self):
        self.coverage["files"][0]["source_id"] = "unknown"
        self.save()
        self.assertTrue(any("lacks a migration entry" in x for x in audit.verify_coverage(self.root)))

    def test_target_symlink_cannot_escape_checkout(self):
        self.target.unlink()
        self.target.symlink_to(self.source_file)
        self.assertTrue(any("unsafe migration target" in x for x in audit.verify_coverage(self.root)))

    def test_unreachable_git_blob_is_still_inspected(self):
        self.git(self.root, "init", "-q")
        oid = self.git(self.root, "hash-object", "-w", "--stdin",
                       input=b"retired-fixture-identity").decode().strip()
        errors, count = audit.history_issues(self.root, "retired-fixture-identity")
        self.assertEqual(count, 1)
        self.assertTrue(any(oid in x for x in errors))

    def test_git_metadata_is_inspected(self):
        self.git(self.root, "init", "-q")
        (self.root / ".git/description").write_text("retired-fixture-identity")
        errors, _ = audit.history_issues(self.root, "retired-fixture-identity")
        self.assertTrue(any("metadata: description" in x for x in errors))


if __name__ == "__main__":
    unittest.main()
