"""Synthetic case lifecycle and safe private journal persistence."""
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from metis.blue import journal as soclog


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "journals"
        self.override = patch.object(soclog, "LOGS_ROOT", self.root)
        self.override.start()
        self.addCleanup(self.override.stop)

    def run_cli(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            soclog.main(list(arguments))
        return output.getvalue(), errors.getvalue()

    def create(self):
        output, _ = self.run_cli("open", "--case", "20300102-unit-case", "--type", "training",
                                 "--title", "Synthetic observation", "--objective", "Preserve provenance")
        self.assertEqual(output.strip(), "20300102-unit-case")
        return output.strip()

    def rows(self, case, name):
        return [json.loads(line) for line in (self.root / case / name).read_text().splitlines()]

    def test_complete_lifecycle_preserves_public_record_shapes(self):
        case = self.create()
        self.run_cli("note", "--case", case, "--text", "Coverage is incomplete", "--host", "asset-1")
        self.run_cli("query", "--case", case, "--platform", "local", "--query", "event.kind=observation",
                     "--purpose", "Check supplied records", "--hits", "3", "--verdict", "useful")
        self.run_cli("finding", "--case", case, "--summary", "An event was recorded",
                     "--evidence", "synthetic.jsonl:3:timestamp", "--attack", "T0000", "--ruled-out", "No execution proof")
        self.run_cli("lesson", "--case", case, "--text", "Retain the raw timezone", "--tag", "clock")
        self.run_cli("close", "--case", case, "--outcome", "inconclusive", "--summary", "Missing process telemetry",
                     "--skills", "soc-triage", "--skills", "soc-triage")
        directory = self.root / case
        meta = json.loads((directory / "meta.json").read_text())
        self.assertEqual(meta["skills"], ["soc-triage"])
        self.assertEqual(meta["outcome"], "inconclusive")
        self.assertTrue(meta["closed_utc"].endswith("Z"))
        query = self.rows(case, "queries.jsonl")[0]
        self.assertEqual(set(query), {"ts", "kind", "platform", "purpose", "query", "hits", "verdict"})
        finding = self.rows(case, "findings.jsonl")[0]
        self.assertEqual(set(finding), {"ts", "kind", "summary", "evidence", "confidence", "attack", "host", "ruled_out"})
        self.assertEqual(finding["confidence"], "medium")
        timeline = self.rows(case, "timeline.jsonl")
        self.assertEqual([entry["kind"] for entry in timeline], ["note", "query", "finding"])
        self.assertEqual(timeline[1]["ts"], query["ts"])
        self.assertEqual(timeline[2]["ts"], finding["ts"])
        self.assertIn("synthetic.jsonl:3:timestamp", (directory / "case.md").read_text())
        self.assertIn(case, (self.root / "INDEX.md").read_text())
        shown, _ = self.run_cli("show", "--case", case)
        self.assertIn("event.kind=observation", shown)
        lessons, _ = self.run_cli("lessons", "--tag", "clock")
        self.assertIn("Retain the raw timezone", lessons)
        self.assertEqual(self.run_cli("lessons", "--tag", "absent")[0], "")
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        for path in directory.iterdir():
            if path.is_file():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_reopen_and_reclose_keep_user_notes_and_refresh_summary(self):
        case = self.create()
        page = self.root / case / "case.md"
        page.write_text(page.read_text().replace("## Hypotheses", "User scope annotation.\n\n## Hypotheses"))
        with page.open("a") as stream:
            stream.write("\n## Later analyst notes\n\nKeep this trailing observation.\n"
                         "\n| outcome | Analyst's earlier hypothesis |\n| closed (UTC) | Unknown |\n")
        self.run_cli("note", "--case", case, "--text", "Retained note")
        self.create()
        self.assertEqual(len(self.rows(case, "timeline.jsonl")), 1)
        for number in range(2):
            self.run_cli("finding", "--case", case, "--summary", f"Observation {number}",
                         "--evidence", f"sample.ndjson:row={number + 1}")
            self.run_cli("close", "--case", case, "--outcome", "inconclusive", "--summary", f"Revision {number}")
        content = page.read_text()
        self.assertIn("User scope annotation.", content)
        self.assertIn("Keep this trailing observation.", content)
        self.assertIn("| outcome | Analyst's earlier hypothesis |", content)
        self.assertIn("| closed (UTC) | Unknown |", content)
        self.assertEqual(content.count("## Outcome"), 1)
        self.assertIn("2 findings", content)
        self.assertIn("Revision 1", content)
        self.assertNotIn("Revision 0", content)

    def test_unmarked_legacy_outcome_and_following_notes_survive_close(self):
        case = self.create()
        page = self.root / case / "case.md"
        page.write_text("# Older private case\n\n## Outcome\n\nEarlier analyst interpretation.\n\n"
                        "## Follow-up\n\nOriginal follow-up remains important.\n")
        for narrative in ("New assessment", "Revised assessment"):
            self.run_cli("close", "--case", case, "--outcome", "inconclusive", "--summary", narrative)
        content = page.read_text()
        self.assertIn("Earlier analyst interpretation.", content)
        self.assertIn("Original follow-up remains important.", content)
        self.assertIn("Revised assessment", content)
        self.assertNotIn("New assessment", content)
        self.assertEqual(content.count("## Outcome"), 1)
        self.assertEqual(content.count(soclog.SUMMARY_START), 1)

    def test_argument_errors_do_not_echo_supplied_values(self):
        private = "password=" + "synthetic" * 4
        for arguments in (("open", "--case", "case", "--type", private),
                          ("index", "--unknown", private),
                          ("query", "--case", "case", "--platform", "local", "--query", "safe", "--hits", private)):
            output, errors = io.StringIO(), io.StringIO()
            with self.subTest(arguments=arguments[0]), redirect_stdout(output), redirect_stderr(errors):
                with self.assertRaises(soclog.ContractError) as caught:
                    soclog.main(list(arguments))
            self.assertNotIn(private, output.getvalue() + errors.getvalue() + str(caught.exception))

    def test_initialization_does_not_replace_preexisting_material(self):
        partial = self.root / "20300102-unit-case"
        partial.mkdir(parents=True)
        for name in ("case.md", "lessons.md", "timeline.jsonl"):
            (partial / name).write_text("preexisting private material\n")
        self.create()
        for name in ("case.md", "lessons.md", "timeline.jsonl"):
            self.assertEqual((partial / name).read_text(), "preexisting private material\n")

    def test_credentials_rejected_in_optional_fields_without_value_disclosure(self):
        case = self.create()
        secret = "password=" + "synthetic" * 4
        for arguments in (
            ("note", "--case", case, "--text", "safe", "--host", secret),
            ("finding", "--case", case, "--summary", "safe", "--evidence", "sample:row=1", "--attack", secret),
            ("lesson", "--case", case, "--text", "safe", "--tag", secret),
            ("close", "--case", case, "--outcome", "inconclusive", "--skills", secret),
        ):
            with self.subTest(command=arguments[0]), self.assertRaises(soclog.ContractError) as caught:
                self.run_cli(*arguments)
            self.assertNotIn(secret, str(caught.exception))
            self.assertNotIn("synthetic", str(caught.exception))
        self.assertEqual(self.rows(case, "timeline.jsonl"), [])
        self.assertIsNone(json.loads((self.root / case / "meta.json").read_text())["closed_utc"])
        self.run_cli("note", "--case", case, "--text", "SHA256=" + "a" * 64)

    def test_short_evidence_is_rejected_without_partial_finding(self):
        case = self.create()
        with self.assertRaises(soclog.ContractError):
            self.run_cli("finding", "--case", case, "--summary", "Unproven", "--evidence", "none")
        self.assertEqual(self.rows(case, "findings.jsonl"), [])
        self.assertEqual(self.rows(case, "timeline.jsonl"), [])

    def test_case_traversal_and_symlink_files_cannot_modify_outside_file(self):
        case = self.create()
        outside = self.base / "outside.txt"
        outside.write_text("keep this value\n")
        with self.assertRaises(soclog.ContractError):
            self.run_cli("note", "--case", "../outside", "--text", "no")
        target = self.root / case / "timeline.jsonl"
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaises(soclog.ContractError):
            self.run_cli("note", "--case", case, "--text", "no")
        self.assertEqual(outside.read_text(), "keep this value\n")
        target.unlink()
        lock = self.root / ".lock"
        lock.unlink()
        lock.symlink_to(outside)
        with self.assertRaises(soclog.ContractError):
            self.run_cli("index")
        self.assertEqual(outside.read_text(), "keep this value\n")

    def test_case_and_root_symlinks_are_rejected(self):
        case = self.create()
        alias = self.root / "alias"
        alias.symlink_to(self.root / case, target_is_directory=True)
        with self.assertRaises(soclog.ContractError):
            self.run_cli("show", "--case", "alias")
        root_alias = self.base / "root-alias"
        root_alias.symlink_to(self.root, target_is_directory=True)
        with patch.object(soclog, "LOGS_ROOT", root_alias), self.assertRaises(soclog.ContractError):
            self.run_cli("index")

    def test_invalid_json_aborts_close_but_incomplete_finding_is_retained(self):
        case = self.create()
        folder = self.root / case
        findings = folder / "findings.jsonl"
        findings.write_text('{"kind":"finding"}\n')
        _, warning = self.run_cli("close", "--case", case, "--outcome", "inconclusive")
        self.assertIn("original record retained", warning)
        self.assertEqual(findings.read_text(), '{"kind":"finding"}\n')
        snapshot = (folder / "meta.json").read_bytes()
        findings.write_text("invalid JSON, private raw value\n")
        with self.assertRaises(soclog.ContractError) as caught:
            self.run_cli("close", "--case", case, "--outcome", "false-positive")
        self.assertNotIn("private raw value", str(caught.exception))
        self.assertEqual((folder / "meta.json").read_bytes(), snapshot)

    def test_concurrent_cli_appends_are_complete_json_records(self):
        case = self.create()
        environment = dict(os.environ, METIS_JOURNAL_ROOT=str(self.root))
        def add(number):
            return subprocess.run([sys.executable, "-m", "metis.blue.journal", "note", "--case", case,
                                   "--text", f"synthetic note {number}"], check=False, env=environment,
                                  capture_output=True, text=True, timeout=15)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(add, range(12)))
        self.assertTrue(all(result.returncode == 0 for result in results), [result.stderr for result in results])
        self.assertEqual({row["text"] for row in self.rows(case, "timeline.jsonl")},
                         {f"synthetic note {number}" for number in range(12)})

    def test_command_function_entrypoints_accept_parsed_arguments(self):
        args = soclog.build_parser().parse_args(["open", "--case", "20300102-unit-case"])
        del args.command
        with redirect_stdout(io.StringIO()):
            soclog.cmd_open(args)
        self.assertTrue(soclog.case_dir("20300102-unit-case").is_dir())


if __name__ == "__main__":
    unittest.main()
