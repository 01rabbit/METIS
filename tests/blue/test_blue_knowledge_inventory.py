import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from metis.blue.runtime import knowledge_intake as intake
from metis.blue.runtime import knowledge_inventory as inventory


class KnowledgeInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # A checkout's parent directory must not affect classification.
        self.source = Path(self.tmp.name).resolve() / "notes"
        self.source.mkdir()
        self.root = self.source.parent / "destination"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.source, check=True)

    def add(self, name, value):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode() if isinstance(value, str) else value)
        subprocess.run(["git", "add", "--", name], cwd=self.source, check=True)
        return path

    def test_metadata_has_no_source_names_text_or_executed_code(self):
        marker = self.source.parent / "executed"
        self.add("private-script.py", f"from pathlib import Path\nPath({str(marker)!r}).touch()\ndef source_only_name():\n    pass\n")
        self.add("private-guide.md", "# A private source heading\n\nA private passage.\n")
        self.add("notes/case.txt", "Raw case material")
        result = inventory.inventory(self.source)
        self.assertEqual(result["summary"]["python"], 1)
        self.assertEqual(result["summary"]["document"], 1)
        self.assertEqual(result["summary"]["case"], 1)
        self.assertFalse(marker.exists())
        encoded = json.dumps(result)
        for text in ("private-script", "source_only_name", "private source heading", "Raw case material"):
            self.assertNotIn(text, encoded)

    def test_fenced_pseudoheadings_are_not_counted_as_document_sections(self):
        text = "# First\n\n````text\n```\n# Still inside code\n````\n\n## Second\n\n####### Not a heading\n"
        sections = inventory.units(text)
        self.assertEqual(len(sections), 2)
        self.assertEqual([s["start_line"] for s in sections], [1, 8])
        self.assertEqual(sum(s["line_count"] for s in sections), len(text.splitlines()))

    def test_unparseable_sources_are_reported_without_a_traceback(self):
        self.add("invalid.py", "def broken(\n")
        self.add("unknown.md", b"\xff\xfe\x00")
        result = inventory.inventory(self.source)
        states = {r.get("parse_status") for r in result["files"]}
        self.assertEqual(states, {"syntax-unavailable", "unsupported-encoding"})

    def test_inventory_changed_during_collection_is_rejected(self):
        path = self.add("entry.md", "# Original\n")
        actual = inventory.safe_read
        def mutate(item, limit):
            raw = actual(item, limit)
            path.write_text("# Changed while collection was running\n")
            return raw
        with mock.patch.object(inventory, "safe_read", side_effect=mutate), self.assertRaises(ValueError):
            inventory.inventory(self.source)

    def test_aggregate_budget_is_enforced(self):
        self.add("entry.md", "A bounded source document.")
        with mock.patch.object(inventory, "MAX_TOTAL", 4), self.assertRaises(ValueError):
            inventory.inventory(self.source)

    def test_cli_rejects_output_aliases_without_writing_the_source(self):
        self.add("entry.md", "A document.")
        private = self.root / intake.PRIVATE
        private.mkdir(parents=True)
        (private / "alias").symlink_to(self.source, target_is_directory=True)
        result = subprocess.run([sys.executable, "-m", "metis.blue.runtime.knowledge_inventory",
                                 "--source", str(self.source), "--root", str(self.root),
                                 "--out", str(private / "alias/report.json")],
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.source / "report.json").exists())
        self.assertNotIn(str(self.source).encode(), result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
