"""Regression tests: canonical intent identity and retry control (Issue #11 follow-up).

The cases reproduce what a Codex specialist did in the ksnctf E2E run: re-running a read by
changing an option that does not change the result, and citing unrelated events as "new evidence".
"""
import struct

import pytest

from metis.core.agent_host import FakeHost
from metis.core.agent_scheduler import FAMILY_LIMIT, AgentScheduler
from metis.core.codex_session import CodexSession
from metis.core.ctf_orchestration import AgentLedger
from metis.core.intent_identity import canonical_data, effective_options, intent_identity


def _pcap(records: int) -> bytes:
    header = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    body = b""
    for index in range(records):
        frame = bytes([index]) * 60
        body += struct.pack("<IIII", index, 0, len(frame), len(frame)) + frame
    return header + body


@pytest.fixture
def env(tmp_path):
    database = tmp_path / ".metis-state" / "metis.sqlite"
    page = tmp_path / "page.html"
    page.write_text("<html>" + "x" * 8000 + "</html>")
    capture = tmp_path / "q.pcap"
    capture.write_bytes(_pcap(5))
    big = tmp_path / "big.bin"
    big.write_bytes(bytes(range(256)) * 400)
    session = CodexSession(database)
    run_id = session.intake(title="Synthetic", description="Recover the hidden message.",
                            paths=[page, capture, big], categories=["crypto", "forensics"], max_actions=200)["run_id"]
    wave = AgentLedger(database).create_wave(run_id)
    scheduler = AgentScheduler(database, FakeHost(script={}, max_parallel=4))
    scheduler.host.script = {role: (lambda a, b: {"state": "hang"}) for role in
                             ("artifact-triage", "crypto-specialist", "forensics-specialist", "independent-critic",
                              "web-specialist", "misc-specialist")}
    scheduler.configure(per_run_slots=4)
    scheduler.enqueue(run_id, wave["wave_id"])
    jobs = scheduler.dispatch(run_id)["started"]
    names = session.context(run_id)["challenge"]["artifacts"]
    return scheduler, run_id, jobs, names, session.artifact_root(run_id)


def _intent(scheduler, run_id, job, payload):
    return scheduler.intent(run_id, job["assignment_id"], job["attempt_id"], payload)


def test_window_longer_than_the_file_is_the_same_request(env):
    scheduler, run_id, jobs, names, _root = env
    page = names[0]
    _intent(scheduler, run_id, jobs[0], {"kind": "artifact", "tool": "text", "artifact": page,
                                         "options": {"offset": 0, "length": 12000}})
    with pytest.raises(ValueError, match="duplicate action"):  # E2E case: 12000 -> 11999 on an 8 KiB page
        _intent(scheduler, run_id, jobs[1], {"kind": "artifact", "tool": "text", "artifact": page,
                                             "options": {"offset": 0, "length": 11999}})
    with pytest.raises(ValueError, match="duplicate action"):  # omitted options equal the defaults
        _intent(scheduler, run_id, jobs[1], {"kind": "artifact", "tool": "text", "artifact": page})


def test_more_packets_than_the_capture_holds_is_the_same_request(env):
    scheduler, run_id, jobs, names, _root = env
    capture = names[1]
    _intent(scheduler, run_id, jobs[0], {"kind": "artifact", "tool": "pcap", "artifact": capture,
                                         "options": {"packets": 200}})
    for packets in (199, "0xc7", 5, 128):  # all read the same five records
        with pytest.raises(ValueError, match="duplicate action"):
            _intent(scheduler, run_id, jobs[1], {"kind": "artifact", "tool": "pcap", "artifact": capture,
                                                 "options": {"packets": packets}})
    fewer = _intent(scheduler, run_id, jobs[1], {"kind": "artifact", "tool": "pcap", "artifact": capture,
                                                 "options": {"packets": 4}})
    assert fewer["observation"]["ok"]


def test_distinct_windows_of_a_large_file_are_different_requests(env):
    scheduler, run_id, jobs, names, _root = env
    big = names[2]
    first = _intent(scheduler, run_id, jobs[0], {"kind": "artifact", "tool": "hex", "artifact": big,
                                                 "options": {"offset": 0, "length": 256}})
    second = _intent(scheduler, run_id, jobs[0], {"kind": "artifact", "tool": "hex", "artifact": big,
                                                  "options": {"offset": 256, "length": 256}})
    assert first["action_identity"] != second["action_identity"]


def test_identity_normalises_types_key_order_and_hex_spelling(env):
    _scheduler, _run_id, _jobs, names, root = env
    assert effective_options(root, names[2], "hex", {"offset": "0x10"}) == \
        effective_options(root, names[2], "hex", {"offset": 16, "length": 256})
    assert canonical_data("gcd", '{"b": 6, "a": "0x0c"}') == canonical_data("gcd", '{"a":12,"b":"6"}')
    assert canonical_data("hex_decode", "41 42\n43") == canonical_data("hex_decode", "414243")
    assert canonical_data("base64_decode", " QUJD") != canonical_data("base64_decode", "QUJD")  # not equivalent
    one = intent_identity("data", "xor", None, {}, '{"data":"6162","key":"01"}', root)
    two = intent_identity("data", "xor", None, {}, '{"key":"01","data":"6162"}', root)
    assert one == two and one[1] is None


def test_retest_needs_an_observation_from_a_different_action_and_is_limited(env):
    scheduler, run_id, jobs, names, _root = env
    page, big = names[0], names[2]
    request = {"kind": "artifact", "tool": "overview", "artifact": page}
    first = _intent(scheduler, run_id, jobs[0], request)
    # E2E case: citing events that are older than the earlier run does not count.
    with pytest.raises(ValueError, match="duplicate action"):
        _intent(scheduler, run_id, jobs[1], {**request, "new_evidence": [first["evidence_sequence"] - 1]})
    # Citing the earlier run of the same request itself does not count either.
    with pytest.raises(ValueError, match="duplicate action"):
        _intent(scheduler, run_id, jobs[1], {**request, "new_evidence": [first["evidence_sequence"]]})
    other = _intent(scheduler, run_id, jobs[1], {"kind": "artifact", "tool": "overview", "artifact": big})
    retest = _intent(scheduler, run_id, jobs[1], {**request, "new_evidence": [other["evidence_sequence"]]})
    assert retest["action_identity"] == first["action_identity"]
    newer = _intent(scheduler, run_id, jobs[1], {"kind": "artifact", "tool": "strings", "artifact": big})
    with pytest.raises(ValueError, match="re-test limit"):
        _intent(scheduler, run_id, jobs[0], {**request, "new_evidence": [newer["evidence_sequence"]]})


def test_variant_limit_per_attempt(env):
    scheduler, run_id, jobs, names, _root = env
    big = names[2]
    for offset in range(FAMILY_LIMIT):
        _intent(scheduler, run_id, jobs[0], {"kind": "artifact", "tool": "hex", "artifact": big,
                                             "options": {"offset": offset * 512}})
    with pytest.raises(ValueError, match="variant limit"):
        _intent(scheduler, run_id, jobs[0], {"kind": "artifact", "tool": "hex", "artifact": big,
                                             "options": {"offset": 9000}})
    # Another tool, or another assignment, is not affected.
    _intent(scheduler, run_id, jobs[0], {"kind": "artifact", "tool": "strings", "artifact": big})
    _intent(scheduler, run_id, jobs[1], {"kind": "artifact", "tool": "hex", "artifact": big,
                                         "options": {"offset": 9000}})


def test_refusals_are_logged(env):
    import sqlite3

    scheduler, run_id, jobs, names, _root = env
    request = {"kind": "artifact", "tool": "overview", "artifact": names[0]}
    _intent(scheduler, run_id, jobs[0], request)
    with pytest.raises(ValueError):
        _intent(scheduler, run_id, jobs[1], request)
    with sqlite3.connect(scheduler.database) as db:
        events = [row[0] for row in db.execute("SELECT event FROM agent_job_log WHERE assignment_id=?",
                                               (jobs[1]["assignment_id"],))]
    assert "intent_duplicate" in events


def test_old_agent_actions_table_is_migrated(tmp_path):
    import sqlite3

    database = tmp_path / "state" / "metis.sqlite"
    database.parent.mkdir()
    with sqlite3.connect(database) as db:
        db.execute("""CREATE TABLE agent_actions (run_id TEXT NOT NULL, identity TEXT NOT NULL,
            assignment_id TEXT NOT NULL, attempt_id TEXT NOT NULL, sequence INTEGER NOT NULL, ok INTEGER NOT NULL,
            time REAL NOT NULL)""")
        db.execute("INSERT INTO agent_actions VALUES ('r','i','a','t',1,1,0)")
    AgentScheduler(database, FakeHost())
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT family FROM agent_actions").fetchall() == [(None,)]
