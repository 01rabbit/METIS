"""Self-created, inert fixtures for bounded offline evidence semantics."""
import copy
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from metis.blue import evidence as a


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="metis-evidence-test-")
        self.root = Path(self.temporary.name).resolve()
        self.counter = 0

    def tearDown(self):
        self.temporary.cleanup()

    def source(self, raw, suffix=".dat"):
        self.counter += 1
        path = self.root / ("input-" + str(self.counter) + suffix)
        path.write_bytes(raw.encode() if isinstance(raw, str) else raw)
        return path

    def check_report(self, kind, raw, **options):
        path = self.source(raw)
        before = path.read_bytes()
        info = path.stat()
        report = a.analyze(kind, path, **options)
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(info.st_mtime_ns, path.stat().st_mtime_ns)
        if "sha256" in report["source"]:
            self.assertEqual(hashlib.sha256(before).hexdigest(), report["source"]["sha256"])
        return report

    def test_json_exact_large_integer_ties_and_lexemes(self):
        r = self.check_report("json", '[{"n":9007199254740993},{"n":9007199254740992},{"n":9007199254740993.0},{"n":9.007199254740993e15}]', field="n")
        self.assertTrue(r["complete_for_input"], r)
        selection = r["data"]["numeric_selection"]
        self.assertEqual(selection["maximum_record_indexes"], [0, 2, 3])
        self.assertEqual(selection["maximum_lexemes"], ["9007199254740993", "9007199254740993.0", "9.007199254740993e15"])
        self.assertEqual(r["data"]["value"]["value"][0]["value"]["n"], {"type": "integer", "lexeme": "9007199254740993"})

    def test_json_object_cannot_masquerade_as_number(self):
        r = self.check_report("json", '[1,{"type":"integer","lexeme":"1"},{"number_type":"integer","lexeme":"1"}]')
        rows = r["data"]["value"]["value"]
        self.assertEqual(rows[0]["type"], "integer")
        self.assertEqual(rows[1]["type"], "object")
        self.assertEqual(rows[2]["type"], "object")
        self.assertNotEqual(rows[0], rows[1])

    def test_json_rejects_duplicate_nonfinite_malformed_and_depth(self):
        for raw, code in [(' {"n":1,"n":2}', "duplicate-json-key"), ('[NaN]', "non-finite-json-number"),
                          ('[Infinity]', "non-finite-json-number"), ('[1,]', "malformed-json"),
                          ('[' * 70 + '0' + ']' * 70, "depth-limit-reached")]:
            with self.subTest(raw=raw[:20]):
                r = self.check_report("json", raw)
                self.assertFalse(r["complete_for_input"])
                self.assertIn(code, r["limitations"])

    def test_json_mixed_population_keeps_invalid_rows_and_negative_maximum(self):
        r = self.check_report("json", '{"rows":[{"n":-4},{"n":true},{"n":"-1"},{},{"n":-3.50}]}', field="n", records_key="rows")
        self.assertFalse(r["complete_for_input"])
        selection = r["data"]["numeric_selection"]
        self.assertEqual(selection["invalid_record_indexes"], [1, 2, 3])
        self.assertEqual(selection["maximum_record_indexes"], [4])

    def test_json_record_byte_and_node_caps_are_not_negative(self):
        for raw, limit, code in [("[1,2,3]", a.Limits(records=2), "record-limit-reached"),
                                 ("[1,2,3]", a.Limits(bytes=3), "input-byte-limit-reached"),
                                 ("[1,2,3]", a.Limits(nodes=2), "node-limit-reached")]:
            r = self.check_report("json", raw, limits=limit)
            self.assertFalse(r["complete_for_input"])
            self.assertIn(code, r["limitations"])

    @staticmethod
    def cloud(event_id="e1", **extra):
        event = {"eventID": event_id, "eventTime": "2026-01-02T03:04:05Z", "eventSource": "s3.amazonaws.com",
                 "eventName": "GetObject", "eventType": "AwsApiCall", "eventCategory": "Data",
                 "userIdentity": {"type": "IAMUser", "principalId": "synthetic-user"}}
        event.update(extra)
        return event

    def test_cloudtrail_deduplication_and_actions_are_explicit(self):
        one = self.cloud()
        rows = [one, copy.deepcopy(one), self.cloud("e2", eventName="ListObjects"),
                self.cloud("e3", userIdentity={"accountId": "anonymous", "type": "AWSAccount"}),
                self.cloud("e4", eventName="ConsoleLogin", eventSource="signin.amazonaws.com", eventCategory="Management", eventType="AwsConsoleSignIn", responseElements={"ConsoleLogin": "Failure"})]
        r = self.check_report("cloudtrail", json.dumps({"Records": rows}))
        self.assertTrue(r["complete_for_input"], r)
        data = r["data"]
        self.assertEqual(data["duplicate_records"], 1)
        self.assertEqual(len(data["records"]), 4)
        by_id = {row["event_id"]: row for row in data["records"]}
        self.assertEqual(by_id["e3"]["authentication"], "anonymous")
        self.assertEqual(by_id["e4"]["outcome"], "failure")
        self.assertEqual(by_id["e1"]["outcome"], "no-recorded-api-error")
        self.assertEqual({row["action"] for row in data["groups"]}, {"GetObject", "ListObjects", "ConsoleLogin"})

    def test_cloudtrail_collisions_missing_ids_and_unknown_identity(self):
        rows = [self.cloud(), self.cloud(eventName="DeleteObject"), self.cloud(None),
                self.cloud("unclassified", userIdentity={"type": ["IAMUser"], "principalId": "claim"})]
        r = self.check_report("cloudtrail", json.dumps(rows))
        self.assertFalse(r["complete_for_input"])
        self.assertEqual(r["data"]["conflicting_event_ids"], ["e1"])
        self.assertEqual(r["data"]["missing_event_id_record_indexes"], [2])
        self.assertEqual([x["event_id"] for x in r["data"]["records"]], ["unclassified"])
        self.assertEqual(r["data"]["records"][0]["authentication"], "unknown")

    def test_cloudtrail_typed_fingerprint_cannot_hide_field_collision(self):
        rows = [self.cloud(requestParameters={"n": 1}), self.cloud(requestParameters={"n": {"number_type": "integer", "lexeme": "1"}})]
        r = self.check_report("cloudtrail", json.dumps(rows))
        self.assertEqual(r["data"]["conflicting_event_ids"], ["e1"])
        self.assertFalse(r["complete_for_input"])

    def test_cloudtrail_time_boundaries_and_precision(self):
        rows = [self.cloud("before", eventTime="2026-01-02T03:04:04Z"), self.cloud("start"),
                self.cloud("end", eventTime="2026-01-02T03:04:06Z")]
        r = self.check_report("cloudtrail", json.dumps(rows), since="2026-01-02T12:04:05+09:00", until="2026-01-02T03:04:06Z")
        self.assertTrue(r["complete_for_input"], r)
        self.assertEqual([x["event_id"] for x in r["data"]["records"]], ["start"])
        self.assertEqual(r["data"]["outside_interval"], 2)
        for options in [{"since": "2026-01-02T03:04:05.0000001Z"}, {"since": "2026-01-02T03:04:05"}]:
            self.assertFalse(self.check_report("cloudtrail", json.dumps(rows), **options)["complete_for_input"])
        self.assertFalse(self.check_report("cloudtrail", json.dumps([self.cloud(eventTime="2026-01-02T03:04:05.0000001Z")]))["complete_for_input"])

    def test_cloudtrail_anonymous_missing_and_success_are_not_conflated(self):
        for identity in ({}, None, {"type": {}}, {"type": "unknown"}, {"type": "anonymous", "arn": "claimed"}):
            self.assertEqual(a.auth_class({"userIdentity": identity}), "unknown")
        self.assertEqual(a.operation_outcome(self.cloud(eventName="ConsoleLogin", responseElements={})), "unknown")
        self.assertEqual(a.operation_outcome(self.cloud(eventName="ConsoleLogin", responseElements={"ConsoleLogin": "Success"})), "recorded-success")
        self.assertEqual(a.operation_outcome(self.cloud(errorCode="AccessDenied")), "failure")

    def test_time_contract_rejects_compact_and_naive_api_bounds(self):
        for value in ["20260102T030405.1234567Z", "2026-01-02T030405.1234567Z",
                      "2026-01-02T03:04:05+00:00:00.1234567", datetime(2026, 1, 2)]:
            r = self.check_report("cloudtrail", json.dumps([self.cloud()]), since=value)
            self.assertFalse(r["complete_for_input"], value)

    def test_email_headers_untrusted_and_attachment_hash(self):
        raw = (b'From: claimed@example.invalid\r\nReceived: from claimed by trusted.example.invalid\r\n'
               b'Authentication-Results: trusted.example.invalid; dkim=pass\r\n'
               b'MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary="test-boundary"\r\n\r\n'
               b'--test-boundary\r\nContent-Type: text/plain\r\n\r\nhttps://example.invalid/do-not-fetch\r\n'
               b'--test-boundary\r\nContent-Type: application/octet-stream\r\nContent-Disposition: attachment; filename="benign.txt"\r\n'
               b'Content-Transfer-Encoding: base64\r\n\r\naW5lcnQ=\r\n--test-boundary--\r\n')
        r = self.check_report("email", raw)
        self.assertTrue(r["complete_for_input"], r)
        self.assertEqual(r["data"]["trust"]["header_assertions"], "unverified")
        self.assertFalse(r["data"]["trust"]["cryptographic_verification"])
        part = r["data"]["messages"][0]["parts"][1]
        self.assertEqual(part["decoded_sha256"], hashlib.sha256(b"inert").hexdigest())
        self.assertEqual(part["coordinate"], "1.2")
        self.assertEqual(list(self.root.iterdir()), [self.root / "input-1.dat"])

    def test_email_mbox_multiple_messages_and_cap(self):
        raw = b"From a@example.invalid Tue Jan  1 00:00:00 2026\nFrom: a@example.invalid\nSubject: one\n\nbody one\n\nFrom b@example.invalid Tue Jan  1 00:00:01 2026\nFrom: b@example.invalid\nSubject: two\n\nbody two\n"
        r = self.check_report("email", raw)
        self.assertTrue(r["complete_for_input"], r)
        self.assertEqual(len(r["data"]["messages"]), 2)
        limited = self.check_report("email", raw, limits=a.Limits(records=1))
        self.assertFalse(limited["complete_for_input"])
        self.assertEqual(len(limited["data"]["messages"]), 1)

    def test_email_unknown_encoding_missing_headers_and_invalid_base64(self):
        for raw, limitation in [(b"From: a@example.invalid\nContent-Transfer-Encoding: unfamiliar\n\nabc", "unsupported-content-transfer-encoding"),
                                (b"", "message-without-headers"),
                                (b"From: a@example.invalid\nContent-Transfer-Encoding: base64\n\na", "message-parse-or-header-defects")]:
            r = self.check_report("email", raw)
            self.assertFalse(r["complete_for_input"], r)
            self.assertIn(limitation, r["limitations"])
            if limitation == "unsupported-content-transfer-encoding":
                self.assertIsNone(r["data"]["messages"][0]["parts"][0]["decoded_sha256"])

    def test_email_conflicting_mime_encoding_cannot_claim_decoded_hash(self):
        raw = b"From: a@example.invalid\nContent-Transfer-Encoding: base64\nContent-Transfer-Encoding: quoted-printable\n\naW5lcnQ="
        r = self.check_report("email", raw)
        self.assertFalse(r["complete_for_input"])
        self.assertIsNone(r["data"]["messages"][0]["parts"][0]["decoded_sha256"])

    @staticmethod
    def event_xml(extra="", time="2026-01-02T03:04:05.1234567Z", system_extra=""):
        return ('<Event xmlns="' + a.EVENT_NS + '"><System><Provider Name="Synthetic.Provider"/>'
                '<EventID>0042</EventID><EventRecordID>9007199254740993</EventRecordID><TimeCreated SystemTime="' + time + '"/>'
                '<Channel>Synthetic</Channel><Computer>fixture.invalid</Computer>' + system_extra + '</System>' + extra + '</Event>')

    def test_event_xml_preserves_precision_location_and_duplicate_data(self):
        first = self.event_xml('<EventData><Data Name="EventID">999</Data><Data Name="value">a</Data><Data Name="value">b</Data></EventData>')
        r = self.check_report("evtx-xml", "<Events>" + first + "</Events>")
        self.assertFalse(r["complete_for_input"])
        row = r["data"]["events"][0]
        self.assertEqual(row["event_id"], 42)
        self.assertEqual(row["event_id_text"], "0042")
        self.assertEqual(row["event_record_id_text"], "9007199254740993")
        self.assertEqual(row["system_time"], "2026-01-02T03:04:05.1234567Z")
        self.assertEqual(row["location"], "/Events/Event[1]")
        self.assertEqual([x["value"] for x in row["event_data"]], ["999", "a", "b"])

    def test_event_xml_valid_system_and_rejected_formats(self):
        r = self.check_report("evtx-xml", self.event_xml())
        self.assertTrue(r["complete_for_input"], r)
        for raw in ['<Events><Other/></Events>', '<?xml version="1.0" encoding="iso-8859-1"?>' + self.event_xml(),
                    '<!DOCTYPE Event [<!ENTITY fixture "inert">]>' + self.event_xml(), b'ElfFile\x00\x00',
                    self.event_xml(system_extra='<EventID>43</EventID>'), self.event_xml(time='2026-02-30T03:04:05Z')]:
            with self.subTest(raw=str(raw)[:45]):
                self.assertFalse(self.check_report("evtx-xml", raw)["complete_for_input"])

    def test_event_xml_partial_parse_and_limit_keep_incompleteness(self):
        raw = "<Events>" + self.event_xml() + "<Event>"
        r = self.check_report("evtx-xml", raw)
        self.assertFalse(r["complete_for_input"])
        self.assertEqual(len(r["data"]["events"]), 1)
        r = self.check_report("evtx-xml", "<Events>" + self.event_xml() * 2 + "</Events>", limits=a.Limits(records=1))
        self.assertFalse(r["complete_for_input"])
        self.assertEqual(len(r["data"]["events"]), 1)

    def make_browser(self, firefox=False, wal=False):
        path = self.root / ("places.sqlite" if firefox else "History")
        connection = sqlite3.connect(path)
        if wal:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA wal_autocheckpoint=0")
        if firefox:
            epoch = 1767323045000000
            connection.executescript("CREATE TABLE moz_places(id INTEGER PRIMARY KEY, url TEXT, title TEXT); CREATE TABLE moz_historyvisits(id INTEGER PRIMARY KEY, place_id INTEGER, visit_date INTEGER);")
            connection.execute("INSERT INTO moz_places VALUES(1, 'https://example.invalid', 'fixture')")
            connection.executemany("INSERT INTO moz_historyvisits VALUES(?,1,?)", [(1, epoch), (2, epoch + 1000000)])
        else:
            epoch = 13411796645000000
            connection.executescript("CREATE TABLE urls(id INTEGER PRIMARY KEY,url TEXT,title TEXT); CREATE TABLE visits(id INTEGER PRIMARY KEY,url INTEGER,visit_time INTEGER); CREATE TABLE downloads(id INTEGER PRIMARY KEY,state INTEGER,start_time INTEGER,end_time INTEGER,received_bytes INTEGER,total_bytes INTEGER); CREATE TABLE downloads_url_chains(id INTEGER,chain_index INTEGER,url TEXT);")
            connection.execute("INSERT INTO urls VALUES(1, 'https://example.invalid', 'fixture')")
            connection.executemany("INSERT INTO visits VALUES(?,1,?)", [(1, epoch), (2, epoch + 1000000)])
            connection.executemany("INSERT INTO downloads VALUES(?,?,?,?,?,?)", [(1, 1, epoch, epoch + 1000000, 5, 5), (2, 3, epoch, 0, 2, 5)])
            connection.execute("INSERT INTO downloads_url_chains VALUES(1,0,'https://example.invalid/file')")
        connection.commit()
        return path, connection

    @staticmethod
    def file_set(path):
        return {suffix: (Path(str(path) + suffix).read_bytes(), Path(str(path) + suffix).stat().st_mtime_ns)
                for suffix in ("", "-wal", "-shm") if Path(str(path) + suffix).exists()}

    def test_browser_chromium_wal_original_unchanged_and_download_semantics(self):
        path, connection = self.make_browser(wal=True)
        try:
            before = self.file_set(path)
            self.assertIn("-wal", before)
            r = a.analyze("browser", path)
            self.assertTrue(r["complete_for_input"], r)
            self.assertEqual(before, self.file_set(path))
            self.assertEqual(len(r["data"]["tables"]["urls"]), 1)
            self.assertEqual(len(r["data"]["tables"]["visits"]), 2)
            downloads = r["data"]["tables"]["downloads"]
            self.assertTrue(downloads[0]["recorded_complete"])
            self.assertFalse(downloads[1]["recorded_complete"])
            self.assertFalse(downloads[0]["downloaded_file_verified"])
            self.assertIn("-wal", r["data"]["snapshot"])
        finally:
            connection.close()

    def test_browser_firefox_epoch_and_interval(self):
        path, connection = self.make_browser(firefox=True)
        connection.close()
        r = a.analyze("browser", path, since="2026-01-02T03:04:05Z", until="2026-01-02T03:04:06Z")
        self.assertTrue(r["complete_for_input"], r)
        self.assertEqual(r["data"]["browser_family"], "firefox")
        self.assertEqual(len(r["data"]["tables"]["moz_places"]), 1)
        visits = r["data"]["tables"]["moz_historyvisits"]
        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0]["visit_date_decoded"]["utc"], "2026-01-02T03:04:05Z")
        self.assertEqual(r["data"]["outside_interval_rows"], 1)

    def test_browser_invalid_times_cannot_disappear_behind_interval(self):
        path, connection = self.make_browser(firefox=True)
        connection.executemany("INSERT INTO moz_historyvisits VALUES(?,1,?)", [(3, None), (4, "invalid"), (5, -4)])
        connection.commit()
        connection.close()
        r = a.analyze("browser", path, since="2026-01-02T03:04:05Z", until="2026-01-02T03:04:06Z")
        self.assertFalse(r["complete_for_input"])
        self.assertIn("invalid-browser-event-time", r["limitations"])
        self.assertEqual(sum(row["in_requested_interval"] is None for row in r["data"]["tables"]["moz_historyvisits"]), 3)

    def test_browser_record_cap_and_inconsistent_completion(self):
        path, connection = self.make_browser()
        connection.execute("UPDATE downloads SET total_bytes=10 WHERE id=1")
        connection.commit()
        connection.close()
        r = a.analyze("browser", path)
        self.assertFalse(r["complete_for_input"])
        self.assertIn("completed-download-metadata-inconsistent", r["limitations"])
        self.assertFalse(r["data"]["tables"]["downloads"][0]["recorded_complete"])
        limited = a.analyze("browser", path, a.Limits(records=2))
        self.assertFalse(limited["complete_for_input"])
        self.assertIn("record-limit-reached", limited["limitations"])

    def test_browser_view_and_missing_column_rejected(self):
        for index, schema in enumerate(["CREATE VIEW urls AS SELECT 1 AS id,'https://example.invalid' AS url; CREATE TABLE visits(id INTEGER,url INTEGER,visit_time INTEGER);", "CREATE TABLE urls(id INTEGER,wrong TEXT); CREATE TABLE visits(id INTEGER,url INTEGER,visit_time INTEGER);"]):
            path = self.root / ("bad" + str(index) + ".sqlite")
            connection = sqlite3.connect(path)
            connection.executescript(schema)
            connection.close()
            r = a.analyze("browser", path)
            self.assertFalse(r["complete_for_input"])
            self.assertNotIn("tables", r["data"])

    def test_input_symlink_and_source_change_rejected(self):
        source = self.source("{}")
        link = self.root / "link.json"
        link.symlink_to(source)
        self.assertFalse(a.analyze("json", link)["complete_for_input"])
        original = a.stamp
        calls = 0
        def changing(path):
            nonlocal calls
            result = original(path)
            calls += 1
            return result if calls < 3 else result[:-1] + (result[-1] + 1,)
        with patch.object(a, "stamp", side_effect=changing):
            r = a.analyze("json", source)
        self.assertFalse(r["complete_for_input"])
        self.assertIn("input-changed-during-analysis", r["limitations"])
        self.assertEqual(source.read_bytes(), b"{}")

    def test_private_writer_confinement_no_overwrite_and_permissions(self):
        target = a.write_private_report(self.root, ".metis-state/reports/one.json", {"synthetic": True})
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
        with self.assertRaises(FileExistsError):
            a.write_private_report(self.root, ".metis-state/reports/one.json", {"synthetic": False})
        self.assertEqual(json.loads(target.read_text()), {"synthetic": True})
        for outside in ["public.json", "../outside.json", ".metis-state/not-json.txt", self.root / "elsewhere.json"]:
            with self.assertRaises(a.EvidenceError):
                a.write_private_report(self.root, outside, {})
        source = self.source("immutable")
        (self.root / ".metis-state" / "redirect").symlink_to(self.root)
        with self.assertRaises(OSError):
            a.write_private_report(self.root, ".metis-state/redirect/new.json", {})
        target = self.root / ".metis-state" / "alias.json"
        os.link(source, target)
        with self.assertRaises(FileExistsError):
            a.write_private_report(self.root, target, {})
        self.assertEqual(source.read_text(), "immutable")
        with self.assertRaises(a.EvidenceError):
            a.write_private_report(self.root, ".metis-state/evidence.json", {}, [self.root / ".metis-state/evidence.json"])
        self.assertFalse(list((self.root / ".metis-state").rglob(".artifact-report-*")))

    def test_cli_private_output_and_incomplete_exit(self):
        import argparse

        def run(*argv):
            parser = argparse.ArgumentParser()
            a.add_arguments(parser)
            return a.run(parser.parse_args(list(argv)), self.root)

        source = self.source('{"synthetic":"private-value"}')
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            status = run("json", str(source), "--out", ".metis-state/good.json")
            self.assertEqual(status, 0)
            self.assertNotIn("private-value", stdout.getvalue())
        bad = self.source('{"x":1,"x":2}')
        with patch("sys.stdout", new_callable=io.StringIO):
            status = run("json", str(bad), "--out", ".metis-state/bad.json")
            self.assertEqual(status, 2)
        self.assertFalse(json.loads((self.root / ".metis-state/bad.json").read_text())["complete_for_input"])

    def test_bytes_entry_matches_path_entry(self):
        raw = b'{"records":[{"n":1},{"n":3},{"n":3}]}'
        by_path = a.analyze("json", self.source(raw), field="n", records_key="records")
        by_bytes = a.analyze_bytes("json", raw, field="n", records_key="records")
        self.assertEqual(by_path["data"], by_bytes["data"])
        self.assertEqual(by_path["source"], by_bytes["source"])

if __name__ == "__main__":
    unittest.main()


def test_evidence_readers_are_run_artifact_tools(tmp_path):
    from metis.core.codex_session import CodexSession
    from metis.core.ctf_artifacts import ARTIFACT_TOOLS, inspect_bytes

    assert {"email", "browser_history", "json_records", "cloudtrail", "evtx_xml"} <= ARTIFACT_TOOLS
    trail = {"Records": [
        {"eventID": "e1", "eventTime": "2026-01-01T00:00:00Z", "eventName": "ConsoleLogin", "eventSource": "signin.amazonaws.com",
         "userIdentity": {"type": "IAMUser", "arn": "arn:aws:iam::111122223333:user/alice"},
         "responseElements": {"ConsoleLogin": "Failure"}},
        {"eventID": "e2", "eventTime": "2026-01-02T00:00:00Z", "eventName": "ConsoleLogin", "eventSource": "signin.amazonaws.com",
         "userIdentity": {"type": "IAMUser", "arn": "arn:aws:iam::111122223333:user/alice"},
         "responseElements": {"ConsoleLogin": "Success"}}]}
    path = tmp_path / "trail.json"
    path.write_text(json.dumps(trail))
    database = tmp_path / ".metis-state" / "metis.sqlite"
    session = CodexSession(database)
    run_id = session.intake(title="Synthetic", description="Find the login.", paths=[path],
                            categories=["forensics"], max_actions=20)["run_id"]
    name = session.context(run_id)["challenge"]["artifacts"][0]
    result = session.artifact(run_id, name, "cloudtrail", {"since": "2026-01-01T12:00:00Z"})
    assert result["ok"], result
    report = inspect_bytes(path.read_bytes(), "cloudtrail", {"since": "2026-01-01T12:00:00Z"})
    assert report["data"]["outside_interval"] == 1 and len(report["data"]["records"]) == 1
    assert "e2" in json.dumps(result)
    report = inspect_bytes(path.read_bytes(), "cloudtrail", {"max_records": 1})
    assert report["complete_for_input"] is False and "record-limit-reached" in report["limitations"]
    with pytest.raises(ValueError):
        inspect_bytes(b"{}", "json_records", {"field": 3})


def test_email_format_option_fails_closed():
    from metis.core.ctf_artifacts import inspect_bytes

    message = b"From: a@example.invalid\r\nSubject: x\r\n\r\nbody\r\n"
    assert inspect_bytes(message, "email", {"email_format": "eml"})["complete_for_input"] is True
    with pytest.raises(ValueError, match="email_format"):
        inspect_bytes(message, "email", {"email_format": "mbx"})
