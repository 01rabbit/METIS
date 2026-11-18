"""Regression tests: canonical intent identity and retry control (Issue #11 follow-up).

The cases reproduce what a Codex specialist did in the ksnctf E2E run: re-running a read by
changing an option that does not change the result, and citing unrelated events as "new evidence".
"""
import base64
import json
import sqlite3
import struct
import threading
import time

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
        _intent(scheduler, run_id, jobs[0], {"kind": "artifact", "tool": "text", "artifact": page,
                                             "options": {"offset": 0, "length": 11999}})
    with pytest.raises(ValueError, match="duplicate action"):  # omitted options equal the defaults
        _intent(scheduler, run_id, jobs[0], {"kind": "artifact", "tool": "text", "artifact": page})


def test_more_packets_than_the_capture_holds_is_the_same_request(env):
    scheduler, run_id, jobs, names, _root = env
    capture = names[1]
    _intent(scheduler, run_id, jobs[0], {"kind": "artifact", "tool": "pcap", "artifact": capture,
                                         "options": {"packets": 200}})
    for packets in (199, "0xc7", 5, 128):  # all read the same five records
        with pytest.raises(ValueError, match="duplicate action"):
            _intent(scheduler, run_id, jobs[0], {"kind": "artifact", "tool": "pcap", "artifact": capture,
                                                 "options": {"packets": packets}})
    fewer = _intent(scheduler, run_id, jobs[0], {"kind": "artifact", "tool": "pcap", "artifact": capture,
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
    assert effective_options(None, None, "zipcrypto_decrypt", {
        "expected_random_header_hex": "DE AD BE EF 00 11 22 33 44 55",
    }) == effective_options(None, None, "zipcrypto_decrypt", {
        "expected_random_header_hex": "deadbeef001122334455",
    })
    assert canonical_data("base64_decode", " QUJD") != canonical_data("base64_decode", "QUJD")  # not equivalent
    one = intent_identity("data", "xor", None, {}, '{"data":"6162","key":"01"}', root)
    two = intent_identity("data", "xor", None, {}, '{"key":"01","data":"6162"}', root)
    assert one == two and one[1] is None


def test_explicit_assignment_artifact_scope_is_enforced_for_intents_and_reports(env):
    scheduler, run_id, jobs, names, _root = env
    job = jobs[0]
    scheduled = next(item for item in scheduler.jobs(run_id)
                     if item["assignment_id"] == job["assignment_id"])
    wave_id = scheduled["wave_id"]
    plan = scheduler.ledger._plan(run_id, wave_id)
    assignment = next(item for item in plan["assignments"] if item["assignment_id"] == job["assignment_id"])

    def save_plan():
        with sqlite3.connect(scheduler.database) as db:
            db.execute("UPDATE ctf_agent_waves SET plan=? WHERE wave_id=?",
                       (json.dumps(plan, sort_keys=True), wave_id))

    assignment["inputs"] = {"artifacts": []}
    save_plan()
    assert scheduler.brief(run_id, assignment, job["attempt_id"])["artifacts"] == []
    with pytest.raises(ValueError, match="outside this assignment's scope"):
        _intent(scheduler, run_id, job, {"kind": "artifact", "tool": "text", "artifact": names[0]})

    assignment["inputs"] = {"artifacts": ["../outside.txt"]}
    save_plan()
    with pytest.raises(ValueError, match="invalid assignment artifact scope"):
        scheduler.brief(run_id, assignment, job["attempt_id"])

    assignment["inputs"] = {"artifacts": [names[0]]}
    save_plan()
    brief = scheduler.brief(run_id, assignment, job["attempt_id"])
    assert brief["artifacts"] == [names[0]]

    remaining = scheduler.session.context(run_id)["actions_remaining"]
    with pytest.raises(ValueError, match="outside this assignment's scope"):
        _intent(scheduler, run_id, job, {"kind": "artifact", "tool": "text", "artifact": names[1]})
    with pytest.raises(ValueError, match="outside this assignment's scope"):
        _intent(scheduler, run_id, job, {"kind": "view", "tool": "image", "artifact": names[1]})
    assert scheduler.session.context(run_id)["actions_remaining"] == remaining

    observed = _intent(scheduler, run_id, job, {"kind": "artifact", "tool": "text", "artifact": names[0]})
    report = {
        "hypothesis": "The assigned text artifact contains the relevant representation.",
        "evidence": "The bounded text reader returned the assigned artifact at the cited event.",
        "falsifier": "A different representation would refute this hypothesis.",
        "next_action": "Inspect the assigned text artifact for its declared encoding.",
        "event_sequences": [observed["evidence_sequence"]],
        "artifact_refs": [names[1]],
        "status": "inconclusive",
    }
    with pytest.raises(ValueError, match="outside this assignment's scope"):
        scheduler.complete(run_id, job["assignment_id"], job["attempt_id"], report)
    assert scheduler.jobs(run_id)[0]["state"] == "running"
    report["artifact_refs"] = [names[0]]
    assert scheduler.complete(run_id, job["assignment_id"], job["attempt_id"], report)["state"] == "completed"


def test_derived_artifact_scope_stays_with_its_creating_assignment(tmp_path):
    database = tmp_path / "state.sqlite"
    source = tmp_path / "source.b64"
    source.write_text(base64.b64encode(b"scoped derived content").decode())
    other = tmp_path / "other.txt"
    other.write_text(base64.b64encode(b"second scoped result").decode())
    session = CodexSession(database)
    run_id = session.intake(title="Scoped derived artifacts", description="Keep derived data local to its worker.",
                            paths=[source, other], categories=["crypto", "forensics"], max_actions=20)["run_id"]
    scheduler = AgentScheduler(database, FakeHost(script={
        role: lambda _assignment, _brief: {"state": "hang"}
        for role in ("crypto-specialist", "forensics-specialist")
    }, max_parallel=2))
    scheduler.configure(global_slots=2, per_run_slots=2)
    plan = scheduler.ledger.create_wave(run_id, mode="delegated")
    by_role = {item["role"]: item for item in plan["assignments"]}
    assignments = [by_role["crypto-specialist"], by_role["forensics-specialist"]]
    plan["assignments"] = assignments
    plan["decision"]["required_roles"] = [item["role"] for item in assignments]
    names = session.context(run_id)["challenge"]["artifacts"]
    assignments[0]["inputs"] = {"artifacts": [names[0]]}
    assignments[1]["inputs"] = {"artifacts": [names[1]]}
    with sqlite3.connect(database) as db:
        db.execute("UPDATE ctf_agent_waves SET plan=? WHERE wave_id=?",
                   (json.dumps(plan, sort_keys=True), plan["wave_id"]))
    scheduler.enqueue(run_id, plan["wave_id"])
    scheduler.dispatch(run_id)
    started = {job["assignment_id"]: job for job in scheduler.jobs(run_id, plan["wave_id"])}
    owner_assignment, other_assignment = assignments
    owner = started[owner_assignment["assignment_id"]]
    non_owner = started[other_assignment["assignment_id"]]

    barrier = threading.Barrier(3)
    derived_results = {}
    failures = []

    def derive_for(key, worker, artifact):
        barrier.wait()
        try:
            derived_results[key] = _intent(scheduler, run_id, worker, {
                "kind": "derive", "tool": "base64_decode", "artifact": artifact,
            })
        except ValueError as exc:
            failures.append((key, exc))

    threads = [threading.Thread(target=derive_for, args=("owner", owner, names[0])),
               threading.Thread(target=derive_for, args=("other", non_owner, names[1]))]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert not failures, failures
    derived_result = derived_results["owner"]
    other_derived_result = derived_results["other"]
    derived = derived_result["observation"]["artifact"]
    other_derived = other_derived_result["observation"]["artifact"]
    updated_plan = scheduler.ledger._plan(run_id, plan["wave_id"])
    updated_assignments = {item["assignment_id"]: item for item in updated_plan["assignments"]}
    assert derived in scheduler.brief(run_id, updated_assignments[owner["assignment_id"]],
                                      owner["attempt_id"])["artifacts"]
    assert derived not in scheduler.brief(run_id, updated_assignments[non_owner["assignment_id"]],
                                          non_owner["attempt_id"])["artifacts"]
    assert other_derived in scheduler.brief(run_id, updated_assignments[non_owner["assignment_id"]],
                                            non_owner["attempt_id"])["artifacts"]
    assert other_derived not in scheduler.brief(run_id, updated_assignments[owner["assignment_id"]],
                                                owner["attempt_id"])["artifacts"]
    with pytest.raises(ValueError, match="outside this assignment's scope"):
        _intent(scheduler, run_id, non_owner, {"kind": "artifact", "tool": "text", "artifact": derived})

    owner_observation = _intent(scheduler, run_id, owner, {
        "kind": "artifact", "tool": "text", "artifact": derived,
    })
    other_observation = _intent(scheduler, run_id, non_owner, {
        "kind": "artifact", "tool": "text", "artifact": other_derived,
    })
    owner_report = {
        "hypothesis": "The assigned decoded artifact contains the expected text.",
        "evidence": "The assigned worker created and read the decoded artifact through bounded tools.",
        "falsifier": "A different decoded representation would refute the hypothesis.",
        "next_action": "Use the decoded content from this assignment only.",
        "event_sequences": [derived_result["evidence_sequence"], owner_observation["evidence_sequence"]],
        "artifact_refs": [names[0], derived], "status": "supported",
    }
    assert scheduler.complete(run_id, owner["assignment_id"], owner["attempt_id"], owner_report)["state"] == "completed"
    other_report = {
        "hypothesis": "The second assigned artifact has a separate representation.",
        "evidence": "A bounded reader inspected the second assignment's own file.",
        "falsifier": "Evidence from the other assignment would not support this hypothesis.",
        "next_action": "Continue with the second assignment's registered file.",
        "event_sequences": [other_derived_result["evidence_sequence"], other_observation["evidence_sequence"]],
        "artifact_refs": [derived], "status": "inconclusive",
    }
    with pytest.raises(ValueError, match="outside this assignment's scope"):
        scheduler.complete(run_id, non_owner["assignment_id"], non_owner["attempt_id"], other_report)
    other_report["artifact_refs"] = [other_derived]
    assert scheduler.complete(run_id, non_owner["assignment_id"], non_owner["attempt_id"],
                               other_report)["state"] == "completed"


def test_concurrent_intents_cannot_exceed_turn_cap(env):
    scheduler, run_id, jobs, names, _root = env
    job = jobs[0]
    with sqlite3.connect(scheduler.database) as db:
        db.execute("UPDATE agent_jobs SET max_turns=1, turns_used=0 WHERE assignment_id=?",
                   (job["assignment_id"],))
    barrier = threading.Barrier(3)
    outcomes = []

    def call(index):
        barrier.wait()
        try:
            outcomes.append(("ok", _intent(scheduler, run_id, job, {
                "kind": "artifact", "tool": "text", "artifact": names[index],
            })))
        except ValueError as exc:
            outcomes.append(("error", str(exc)))

    threads = [threading.Thread(target=call, args=(index,)) for index in (0, 1)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert sum(kind == "ok" for kind, _ in outcomes) == 1
    assert sum(kind == "error" and "max turns" in result for kind, result in outcomes) == 1
    actual = next(item for item in scheduler.jobs(run_id) if item["assignment_id"] == job["assignment_id"])
    assert actual["turns_used"] == 1


def test_derived_persistence_and_scope_commit_precede_concurrent_cancel(tmp_path, monkeypatch):
    database = tmp_path / "state.sqlite"
    source = tmp_path / "source.b64"
    source.write_text(base64.b64encode(b"committed only with scope").decode())
    session = CodexSession(database)
    run_id = session.intake(title="Derived commit", description="Atomic scope commit.",
                            paths=[source], max_actions=20)["run_id"]
    scheduler = AgentScheduler(database, FakeHost(script={
        role: lambda _assignment, _brief: {"state": "hang"}
        for role in ("crypto-specialist", "forensics-specialist")
    }, max_parallel=2))
    scheduler.configure(global_slots=2, per_run_slots=2)
    plan = scheduler.ledger.create_wave(run_id, mode="delegated")
    assignments = plan["assignments"][:2]
    plan["assignments"] = assignments
    plan["decision"]["required_roles"] = [item["role"] for item in assignments]
    names = session.context(run_id)["challenge"]["artifacts"]
    assignments[0]["inputs"] = {"artifacts": [names[0]]}
    assignments[1]["inputs"] = {"artifacts": []}
    with sqlite3.connect(database) as db:
        db.execute("UPDATE ctf_agent_waves SET plan=? WHERE wave_id=?",
                   (json.dumps(plan, sort_keys=True), plan["wave_id"]))
    scheduler.enqueue(run_id, plan["wave_id"])
    scheduler.dispatch(run_id)
    owner = next(job for job in scheduler.jobs(run_id, plan["wave_id"])
                 if job["assignment_id"] == assignments[0]["assignment_id"])

    stored = threading.Event()
    release = threading.Event()
    original_store = scheduler.session.store_artifact

    def paused_store(*args, **kwargs):
        artifact = original_store(*args, **kwargs)
        stored.set()
        assert release.wait(5)
        return artifact

    monkeypatch.setattr(scheduler.session, "store_artifact", paused_store)
    result = {}
    errors = []
    def run_derive():
        try:
            result["intent"] = _intent(scheduler, run_id, owner, {
                "kind": "derive", "tool": "base64_decode", "artifact": names[0]})
        except ValueError as exc:
            errors.append(exc)

    intent_thread = threading.Thread(target=run_derive)
    intent_thread.start()
    assert stored.wait(5), errors
    cancel_done = threading.Event()
    cancel_thread = threading.Thread(target=lambda: (scheduler.cancel(assignment_id=owner["assignment_id"],
                                                                      reason="race test"), cancel_done.set()))
    cancel_thread.start()
    assert not cancel_done.wait(0.1)
    release.set()
    intent_thread.join(timeout=5)
    cancel_thread.join(timeout=5)
    assert not intent_thread.is_alive() and not cancel_thread.is_alive()
    derived = result["intent"]["observation"]["artifact"]
    updated_plan = scheduler.ledger._plan(run_id, plan["wave_id"])
    scoped = next(item for item in updated_plan["assignments"]
                  if item["assignment_id"] == owner["assignment_id"])
    unscoped = next(item for item in updated_plan["assignments"]
                    if item["assignment_id"] == assignments[1]["assignment_id"])
    assert derived in scoped["inputs"]["artifacts"]
    assert derived not in unscoped["inputs"]["artifacts"]
    assert derived in session.context(run_id)["challenge"]["artifacts"]


def test_concurrent_intent_observations_keep_their_own_sequences(env, monkeypatch):
    scheduler, run_id, jobs, names, _root = env
    first_job, second_job = jobs[:2]
    original_artifact = scheduler.session.artifact
    first_observed = threading.Event()
    release_first = threading.Event()
    emitted = {}

    def paused_artifact(operation_run, name, tool, options=None, **kwargs):
        result = original_artifact(operation_run, name, tool, options, **kwargs)
        emitted[name] = result["_evidence_sequence"]
        if kwargs.get("_owner") == (first_job["assignment_id"], first_job["attempt_id"]):
            first_observed.set()
            assert release_first.wait(5)
        return result

    monkeypatch.setattr(scheduler.session, "artifact", paused_artifact)
    first_result = {}
    first_error = []

    def run_first():
        try:
            first_result["value"] = _intent(scheduler, run_id, first_job, {
                "kind": "artifact", "tool": "text", "artifact": names[0]})
        except ValueError as exc:
            first_error.append(exc)

    thread = threading.Thread(target=run_first)
    thread.start()
    assert first_observed.wait(5)
    second = _intent(scheduler, run_id, second_job, {
        "kind": "artifact", "tool": "text", "artifact": names[1]})
    release_first.set()
    thread.join(timeout=5)
    assert not thread.is_alive() and not first_error
    first = first_result["value"]
    assert first["evidence_sequence"] == emitted[names[0]]
    assert second["evidence_sequence"] == emitted[names[1]]
    assert first["evidence_sequence"] != second["evidence_sequence"]
    with sqlite3.connect(scheduler.database) as db:
        persisted = db.execute("SELECT identity,sequence FROM agent_actions WHERE run_id=?",
                               (run_id,)).fetchall()
    by_identity = dict(persisted)
    assert by_identity[first["action_identity"]] == first["evidence_sequence"]
    assert by_identity[second["action_identity"]] == second["evidence_sequence"]


def test_cancel_during_inflight_intent_returns_and_discards_late_result(env, monkeypatch):
    scheduler, run_id, jobs, names, _root = env
    job = jobs[0]
    entered, release = threading.Event(), threading.Event()
    from metis.core import codex_session

    def blocked_inspect(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return {"format": "TEXT", "text": "bounded result"}

    monkeypatch.setattr(codex_session, "inspect_file", blocked_inspect)
    intent_result, intent_error, cancel_result = [], [], []
    def run_intent():
        try:
            intent_result.append(_intent(scheduler, run_id, job, {
                "kind": "artifact", "tool": "text", "artifact": names[0],
            }))
        except ValueError as exc:
            intent_error.append(str(exc))

    intent_thread = threading.Thread(target=run_intent)
    intent_thread.start()
    assert entered.wait(timeout=10)
    cancel_done = threading.Event()
    def run_cancel():
        cancel_result.extend(scheduler.cancel(assignment_id=job["assignment_id"]))
        cancel_done.set()

    cancel_thread = threading.Thread(target=run_cancel)
    cancel_thread.start()
    assert cancel_done.wait(timeout=2), "cancel must not wait for the long-running intent lock"
    release.set()
    intent_thread.join(timeout=10)
    cancel_thread.join(timeout=10)
    assert not intent_result and intent_error
    assert cancel_result[0]["state"] == "cancelled"
    with pytest.raises(ValueError, match="stale or unknown attempt"):
        _intent(scheduler, run_id, job, {"kind": "artifact", "tool": "hex", "artifact": names[1]})


def test_deadline_during_intent_cancels_and_discards_late_result(env, monkeypatch):
    scheduler, run_id, jobs, names, _root = env
    job = jobs[0]
    entered, release = threading.Event(), threading.Event()
    from metis.core import codex_session

    def blocked_inspect(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return {"format": "TEXT", "text": "late result"}

    monkeypatch.setattr(codex_session, "inspect_file", blocked_inspect)
    errors = []
    def run_intent():
        try:
            _intent(scheduler, run_id, job, {"kind": "artifact", "tool": "text", "artifact": names[0]})
        except ValueError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=run_intent)
    thread.start()
    assert entered.wait(timeout=10)
    with sqlite3.connect(scheduler.database) as db:
        db.execute("UPDATE agent_jobs SET deadline=? WHERE assignment_id=?", (time.time() - 1, job["assignment_id"]))
    changes = scheduler.tick()
    assert any(item["assignment_id"] == job["assignment_id"] and item["state"] == "timed_out"
               for item in changes)
    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive() and errors
    actual = next(item for item in scheduler.jobs(run_id) if item["assignment_id"] == job["assignment_id"])
    assert actual["state"] == "timed_out"
    with sqlite3.connect(scheduler.database) as db:
        assert db.execute("SELECT COUNT(*) FROM agent_actions WHERE assignment_id=?", (job["assignment_id"],)
                          ).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM agent_action_reservations WHERE assignment_id=?",
                          (job["assignment_id"],)).fetchone()[0] == 0


def test_retest_needs_an_observation_from_a_different_action_and_is_limited(env):
    scheduler, run_id, jobs, names, _root = env
    jobs = [max(jobs, key=lambda job: job["brief"]["max_turns"])]  # five intents fit a six-turn job
    page, big = names[0], names[2]
    request = {"kind": "artifact", "tool": "overview", "artifact": page}
    first = _intent(scheduler, run_id, jobs[0], request)
    # E2E case: citing events that are older than the earlier run does not count.
    with pytest.raises(ValueError, match="duplicate action"):
        _intent(scheduler, run_id, jobs[0], {**request, "new_evidence": [first["evidence_sequence"] - 1]})
    # Citing the earlier run of the same request itself does not count either.
    with pytest.raises(ValueError, match="duplicate action"):
        _intent(scheduler, run_id, jobs[0], {**request, "new_evidence": [first["evidence_sequence"]]})
    other = _intent(scheduler, run_id, jobs[0], {"kind": "artifact", "tool": "overview", "artifact": big})
    retest = _intent(scheduler, run_id, jobs[0], {**request, "new_evidence": [other["evidence_sequence"]]})
    assert retest["action_identity"] == first["action_identity"]
    newer = _intent(scheduler, run_id, jobs[0], {"kind": "artifact", "tool": "strings", "artifact": big})
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
        _intent(scheduler, run_id, jobs[0], request)
    with sqlite3.connect(scheduler.database) as db:
        events = [row[0] for row in db.execute("SELECT event FROM agent_job_log WHERE assignment_id=?",
                                               (jobs[0]["assignment_id"],))]
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


def test_other_attempts_may_replay_but_a_run_caps_identical_actions(env, monkeypatch):
    """Stateless specialists cannot read each other's observations: a new attempt may re-run an
    action once, but one canonical action runs at most RUN_REPLAY_LIMIT times per run."""
    from metis.core import agent_scheduler

    monkeypatch.setattr(agent_scheduler, "RUN_REPLAY_LIMIT", 3)  # production value: 8
    RUN_REPLAY_LIMIT = 3
    scheduler, run_id, jobs, names, _root = env
    request = {"kind": "artifact", "tool": "overview", "artifact": names[0]}
    assert len(jobs) > RUN_REPLAY_LIMIT
    for job in jobs[:RUN_REPLAY_LIMIT]:
        _intent(scheduler, run_id, job, request)
    with pytest.raises(ValueError, match=f"already ran {RUN_REPLAY_LIMIT} times"):
        _intent(scheduler, run_id, jobs[RUN_REPLAY_LIMIT], request)
