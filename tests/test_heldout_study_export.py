"""Controller-derived, answer-free held-out export checks."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from metis.core.agent_host import FakeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession
from metis.core.codex_specialist import CodexCLI, CodexTurn, run_assignment
from metis.core.contracts import ChallengeManifest
from metis.core.ctf_knowledge import KnowledgeBase, TechniqueCard
from metis.core.ctf_orchestration import AgentLedger
from metis.core.store import RunStore
from metis.evaluation.heldout_analysis import reconcile_evidence
from metis.evaluation.heldout_protocol import (
    Bindings,
    Protocol,
    bind_run,
    digest,
    finalize,
    main,
    schedule,
)
from metis.evaluation.heldout_study_export import ExportManifest, export

REAL_PROMPT = "Use only the scoped METIS tools and report bounded evidence."
REAL_PROMPT_SHA256 = hashlib.sha256(REAL_PROMPT.encode()).hexdigest()


def real_prompt_config(data: dict) -> dict:
    for config in data["arm_config"].values():
        config["prompt_sha256"] = REAL_PROMPT_SHA256
    return data


def fixture(tmp_path: Path) -> tuple[Path, ExportManifest]:
    dbpath = tmp_path / "state.sqlite"
    with sqlite3.connect(dbpath) as db:
        db.execute("CREATE TABLE events (run_id TEXT, sequence INTEGER, payload TEXT, "
                   "timestamp TEXT, previous_hash TEXT, digest TEXT)")
        db.execute("CREATE TABLE codex_sessions (run_id TEXT, evaluation_split TEXT, started REAL)")
        db.execute("CREATE TABLE agent_jobs (assignment_id TEXT, run_id TEXT, state TEXT, "
                   "usage TEXT, model TEXT)")
        db.execute("CREATE TABLE ctf_agent_reports (assignment_id TEXT, run_id TEXT)")
        db.execute("CREATE TABLE agent_turn_reservations (run_id TEXT, assignment_id TEXT, "
                   "attempt_id TEXT DEFAULT '-')")
        for index in range(8):
            run_id = f"{index + 1:032x}"
            db.execute("INSERT INTO codex_sessions VALUES (?,?,?)", (run_id, "heldout", 10.0))
            assignment_id = f"assignment-{index}"
            db.execute("INSERT INTO agent_jobs VALUES (?,?,?,?,?)", (
                assignment_id, run_id, "completed", json.dumps({"input_tokens": 3, "output_tokens": 2}),
                "test-model"))
            db.execute("INSERT INTO ctf_agent_reports VALUES (?,?)", (assignment_id, run_id))
            db.execute("INSERT INTO agent_turn_reservations(run_id,assignment_id) VALUES (?,?)", (run_id, assignment_id))
            previous = ""
            for sequence, (status, detail) in enumerate([
                ("new", {}), ("executing", {"tool": "text"}),
                ("solved", {"verification": "local_fixture_oracle"}),
            ]):
                payload = json.dumps({"schema_version": 1, "run_id": run_id,
                                      "sequence": sequence, "status": status, "detail": detail})
                timestamp = f"2026-01-01T00:00:{sequence:02d}+00:00"
                digest = RunStore._digest(payload, timestamp, previous)
                db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (
                    run_id, sequence, payload, timestamp, previous, digest))
                previous = digest
    runs = [{"task_id": f"task{index // 4}", "repetition": (index // 2) % 2,
             "arm": ("full" if index % 2 == 0 else "single_agent"),
             "run_id": f"{index + 1:032x}"} for index in range(8)]
    budget = {"model_calls": 4, "tokens": 100, "actions": 4,
              "seconds": 60.0, "cost_usd": None}
    manifest = ExportManifest.model_validate({
        "schema_version": 1, "study_id": "synthetic-export", "measurement": "synthetic_fixture",
        "model_pin": "test-model", "runtime_pin": "test-runtime", "seed": 1,
        "repetitions": 2, "arms": ["full", "single_agent"], "baseline": "single_agent",
        "budgets": {"full": budget, "single_agent": budget},
        "tasks": [{"task_id": f"task{i}", "category": "crypto", "difficulty": "easy",
                   "split": "held_out", "exposure": "unseen",
                   "solvability_control_verified": True} for i in range(2)],
        "runs": runs,
    })
    return dbpath, manifest


def attest_fixture(database: Path, protocol: Protocol, bindings: Bindings) -> None:
    """Supply synthetic dispatch rows for exporter-specific fixtures."""
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE heldout_arm_bindings (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("CREATE TABLE agent_job_log (assignment_id TEXT, event TEXT, detail TEXT, "
                   "attempt_id TEXT DEFAULT '-')")
        for run in bindings.runs:
            config = protocol.arm_config[run.arm]
            record = {"protocol_sha256": digest(protocol), "task_id": run.task_id,
                      "repetition": run.repetition, "arm": run.arm,
                      "arm_config": config.model_dump(mode="json"),
                      "model_pin": protocol.model_pin, "runtime_pin": protocol.runtime_pin,
                      "budget": protocol.budgets[run.arm].model_dump(mode="json"),
                      "prompt_text": REAL_PROMPT}
            db.execute("INSERT INTO heldout_arm_bindings VALUES (?,?)",
                       (run.run_id, json.dumps(record, sort_keys=True)))
            applied = {"protocol_sha256": digest(protocol), "arm": run.arm,
                       "memory_cards": len(protocol.memory_card_digests) if config.memory_enabled else 0,
                       "model": protocol.model_pin, "runtime": protocol.runtime_pin}
            db.execute("INSERT INTO agent_job_log(assignment_id,event,detail) VALUES (?,?,?)",
                       (f"assignment-{int(run.run_id, 16) - 1}", "heldout_arm_applied",
                        json.dumps(applied, sort_keys=True)))
            identity = db.execute("SELECT rowid FROM agent_turn_reservations WHERE run_id=?",
                                  (run.run_id,)).fetchone()[0]
            db.execute("INSERT INTO agent_job_log(assignment_id,event,detail) VALUES (?,?,?)",
                       (f"assignment-{int(run.run_id, 16) - 1}", "heldout_prompt_applied",
                        json.dumps({"reservation_id": identity, "prefix_sha256": REAL_PROMPT_SHA256,
                                    "prompt_sha256": REAL_PROMPT_SHA256, "model": protocol.model_pin,
                                    "runtime": protocol.runtime_pin})))
            db.execute("INSERT INTO agent_job_log(assignment_id,event,detail) VALUES (?,?,?)",
                       (f"assignment-{int(run.run_id, 16) - 1}", "codex_turn",
                        json.dumps({"reservation_id": identity})))


def test_export_derives_outcome_and_resources(tmp_path: Path) -> None:
    database, manifest = fixture(tmp_path)
    study = export(manifest, database)
    assert len(study.trials) == 8
    assert all(trial.oracle == "protected_fixture" and trial.oracle_verified
               and trial.workflow_complete and trial.failure == "none"
               and trial.model_calls == 1 and trial.actions == 1
               and trial.tokens == 5 and trial.cost_usd is None
               for trial in study.trials)
    assert reconcile_evidence(study, database)["protected_fixture_verified_trials"] == 8


def test_export_rejects_corrupt_chain(tmp_path: Path) -> None:
    database, manifest = fixture(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE events SET digest='invalid' WHERE run_id=? AND sequence=1",
                   (manifest.runs[0].run_id,))
    with pytest.raises(ValueError, match="event chain is corrupt"):
        export(manifest, database)


def test_export_rejects_split_and_matrix_mismatch(tmp_path: Path) -> None:
    database, manifest = fixture(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE codex_sessions SET evaluation_split='development' WHERE run_id=?",
                   (manifest.runs[0].run_id,))
    with pytest.raises(ValueError, match="split"):
        export(manifest, database)
    data = manifest.model_dump()
    data["runs"] = data["runs"][:-1]
    with pytest.raises(ValueError, match="at least 8"):
        ExportManifest.model_validate(data)


def test_export_does_not_trust_missing_usage_or_unverified_end(tmp_path: Path) -> None:
    database, manifest = fixture(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE agent_jobs SET usage=NULL WHERE run_id=?", (manifest.runs[0].run_id,))
    study = export(manifest, database)
    assert study.trials[0].tokens is None


def test_real_model_pin_must_match_job_records(tmp_path: Path) -> None:
    database, manifest = fixture(tmp_path)
    data = manifest.model_dump()
    data["measurement"] = "real_model"
    real_manifest = ExportManifest.model_validate(data)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE agent_jobs SET model='other-model' WHERE run_id=?",
                   (manifest.runs[0].run_id,))
    with pytest.raises(ValueError, match="model pin"):
        export(real_manifest, database)


def test_verified_event_without_completed_report_does_not_score(tmp_path: Path) -> None:
    database, manifest = fixture(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM ctf_agent_reports WHERE run_id=?", (manifest.runs[0].run_id,))
    trial = export(manifest, database).trials[0]
    assert trial.oracle_verified is True
    assert trial.workflow_complete is False
    assert trial.failure == "incomplete"


def _protocol_fixture(tmp_path: Path) -> tuple[Path, Protocol, Bindings]:
    database, manifest = fixture(tmp_path)
    data = manifest.model_dump()
    runs = data.pop("runs")
    for index, task in enumerate(data["tasks"]):
        task["source_id"] = f"local-fixture-{index}"
        task["distribution_sha256"] = f"{index + 10:064x}"
    data["arm_config"] = {
        "full": {"memory_enabled": True, "planner_enabled": True,
                 "max_specialists": 2, "prompt_sha256": "a" * 64},
        "single_agent": {"memory_enabled": True, "planner_enabled": True,
                         "max_specialists": 1, "prompt_sha256": "b" * 64},
    }
    protocol = Protocol.model_validate(data)
    ordered = sorted(runs, key=lambda run: next(
        index for index, slot in enumerate(schedule(protocol))
        if (slot["task_id"], slot["repetition"], slot["arm"]) ==
        (run["task_id"], run["repetition"], run["arm"])))
    bindings = Bindings.model_validate({"protocol_sha256": digest(protocol), "runs": ordered})
    return database, protocol, bindings


def test_protocol_finalizes_frozen_matrix_with_controller_evidence(tmp_path: Path) -> None:
    database, protocol, bindings = _protocol_fixture(tmp_path)
    result = finalize(protocol, bindings, database, expected_sha256=digest(protocol))
    assert result["protocol_sha256"] == digest(protocol)
    assert result["ledger_reconciliation"]["trials_reconciled"] == 8
    assert result["analysis"]["arms"]["full"]["scored_solves"] == 4
    assert result["analysis"]["arms"]["full"]["acceptance_eligible_solves"] == 0
    assert "private result" not in json.dumps(result)


def test_protocol_rejects_mutation_order_and_missing_binding(tmp_path: Path) -> None:
    database, protocol, bindings = _protocol_fixture(tmp_path)
    changed = protocol.model_copy(update={"seed": protocol.seed + 1})
    with pytest.raises(ValueError, match="commitment"):
        finalize(changed, bindings, database, expected_sha256=digest(protocol))
    reversed_bindings = bindings.model_copy(update={"runs": list(reversed(bindings.runs))})
    with pytest.raises(ValueError, match="schedule"):
        finalize(protocol, reversed_bindings, database, expected_sha256=digest(protocol))
    missing = bindings.model_copy(update={"runs": bindings.runs[:-1]})
    with pytest.raises(ValueError):
        finalize(protocol, missing, database, expected_sha256=digest(protocol))
    changed_source = protocol.model_dump()
    changed_source["tasks"][0]["distribution_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="commitment"):
        finalize(Protocol.model_validate(changed_source), bindings, database,
                 expected_sha256=digest(protocol))


def test_protocol_rejects_mislabeled_ablation(tmp_path: Path) -> None:
    _, protocol, _ = _protocol_fixture(tmp_path)
    data = protocol.model_dump()
    data["arm_config"]["single_agent"]["max_specialists"] = 2
    with pytest.raises(ValueError, match="arm configuration"):
        Protocol.model_validate(data)


def test_memory_ablation_requires_committed_cards_and_exact_arm_snapshots(tmp_path: Path) -> None:
    database, original, original_bindings = _protocol_fixture(tmp_path)
    data = original.model_dump()
    data["measurement"] = "real_model"
    data["arms"] = ["full", "without_memory"]
    data["baseline"] = "full"
    data["budgets"]["without_memory"] = data["budgets"].pop("single_agent")
    data["arm_config"]["without_memory"] = {
        "memory_enabled": False, "planner_enabled": True,
        "max_specialists": 2, "prompt_sha256": "a" * 64,
    }
    data["arm_config"].pop("single_agent")
    real_prompt_config(data)
    with pytest.raises(ValueError, match="requires frozen prior cards"):
        Protocol.model_validate(data)
    payload = '{"category":"crypto","source_split":"practice"}'
    card_digest = hashlib.sha256(payload.encode()).hexdigest()
    data["memory_card_digests"] = [card_digest]
    protocol = Protocol.model_validate(data)
    runs = [item.model_dump() for item in original_bindings.runs]
    for item in runs:
        if item["arm"] == "single_agent":
            item["arm"] = "without_memory"
    ordering = {(slot["task_id"], slot["repetition"], slot["arm"]): index
                for index, slot in enumerate(schedule(protocol))}
    runs.sort(key=lambda item: ordering[(item["task_id"], item["repetition"], item["arm"])])
    bindings = Bindings.model_validate({"protocol_sha256": digest(protocol), "runs": runs})
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE munin_cards (id INTEGER, payload TEXT, digest TEXT, source_split TEXT, created REAL)")
        db.execute("INSERT INTO munin_cards VALUES (?,?,?,?,?)",
                   (1, payload, card_digest, "practice", 1.0))
        db.execute("CREATE TABLE heldout_memory_snapshots (run_id TEXT, card_id INTEGER, payload TEXT, digest TEXT)")
        db.executemany("INSERT INTO heldout_memory_snapshots VALUES (?,?,?,?)",
                       [(item["run_id"], 1, payload, card_digest) for item in runs if item["arm"] == "full"])
    attest_fixture(database, protocol, bindings)
    assert finalize(protocol, bindings, database, expected_sha256=digest(protocol))["protocol_sha256"] == digest(protocol)
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO heldout_memory_snapshots VALUES (?,?,?,?)",
                   (next(item["run_id"] for item in runs if item["arm"] == "without_memory"),
                    1, payload, card_digest))
    with pytest.raises(ValueError, match="conflicts with arm"):
        finalize(protocol, bindings, database, expected_sha256=digest(protocol))
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM heldout_memory_snapshots WHERE run_id=?",
                   (next(item["run_id"] for item in runs if item["arm"] == "without_memory"),))
        db.execute("UPDATE heldout_memory_snapshots SET payload='{}' WHERE run_id=?",
                   (next(item["run_id"] for item in runs if item["arm"] == "full"),))
    with pytest.raises(ValueError, match="digest mismatch"):
        finalize(protocol, bindings, database, expected_sha256=digest(protocol))


def test_real_model_rejects_missing_or_changed_arm_dispatch(tmp_path: Path) -> None:
    database, original, bindings = _protocol_fixture(tmp_path)
    real = Protocol.model_validate(real_prompt_config({**original.model_dump(), "measurement": "real_model"}))
    bound = bindings.model_copy(update={"protocol_sha256": digest(real)})
    with pytest.raises(ValueError, match="arm binding mismatch"):
        finalize(real, bound, database, expected_sha256=digest(real))
    attest_fixture(database, real, bound)
    with sqlite3.connect(database) as db:
            db.execute("UPDATE agent_job_log SET detail=? WHERE assignment_id='assignment-0' "
                       "AND event='heldout_arm_applied'",
                   (json.dumps({"arm": "without_memory"}),))
    with pytest.raises(ValueError, match="dispatch treatment mismatch"):
        finalize(real, bound, database, expected_sha256=digest(real))


def test_real_model_rejects_arm_evidence_from_other_attempt(tmp_path: Path) -> None:
    database, original, bindings = _protocol_fixture(tmp_path)
    real = Protocol.model_validate(real_prompt_config({**original.model_dump(), "measurement": "real_model"}))
    bound = bindings.model_copy(update={"protocol_sha256": digest(real)})
    attest_fixture(database, real, bound)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE agent_job_log SET attempt_id='other' WHERE assignment_id='assignment-0' "
                   "AND event='heldout_arm_applied'")
    with pytest.raises(ValueError, match="dispatch treatment mismatch"):
        finalize(real, bound, database, expected_sha256=digest(real))


@pytest.mark.parametrize("mutation", ["missing_retry_prompt", "duplicate_prompt", "failed_missing_prompt",
                                      "wrong_model", "unmatched_prompt"])
def test_real_model_requires_one_prompt_for_every_dispatched_turn(tmp_path: Path, mutation: str) -> None:
    database, original, bindings = _protocol_fixture(tmp_path)
    real = Protocol.model_validate(real_prompt_config({**original.model_dump(), "measurement": "real_model"}))
    bound = bindings.model_copy(update={"protocol_sha256": digest(real)})
    attest_fixture(database, real, bound)
    with sqlite3.connect(database) as db:
        assignment = "assignment-0"
        db.execute("INSERT INTO agent_turn_reservations(run_id,assignment_id) VALUES (?,?)",
                   (bindings.runs[0].run_id, assignment))
        identity = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        prompt = {"reservation_id": identity, "prefix_sha256": REAL_PROMPT_SHA256,
                  "prompt_sha256": REAL_PROMPT_SHA256, "model": real.model_pin, "runtime": real.runtime_pin}
        if mutation == "wrong_model":
            prompt["model"] = "other-model"
        if mutation not in {"missing_retry_prompt", "failed_missing_prompt"}:
            db.execute("INSERT INTO agent_job_log(assignment_id,event,detail) VALUES (?,?,?)",
                       (assignment, "heldout_prompt_applied", json.dumps(prompt)))
        db.execute("INSERT INTO agent_job_log(assignment_id,event,detail) VALUES (?,?,?)",
                   (assignment, "codex_turn", json.dumps({"reservation_id": identity})))
        if mutation == "duplicate_prompt":
            db.execute("INSERT INTO agent_job_log(assignment_id,event,detail) VALUES (?,?,?)",
                       (assignment, "heldout_prompt_applied", json.dumps(prompt)))
        if mutation == "failed_missing_prompt":
            db.execute("UPDATE agent_jobs SET state='failed' WHERE assignment_id=?", (assignment,))
        if mutation == "unmatched_prompt":
            db.execute("INSERT INTO agent_job_log(assignment_id,event,detail) VALUES (?,?,?)",
                       (assignment, "heldout_prompt_applied", json.dumps({**prompt, "reservation_id": 999999})))
    with pytest.raises(ValueError, match="prompt dispatch mismatch"):
        finalize(real, bound, database, expected_sha256=digest(real))


def test_real_model_accepts_attested_retry_and_pre_dispatch_stop(tmp_path: Path) -> None:
    database, original, bindings = _protocol_fixture(tmp_path)
    real = Protocol.model_validate(real_prompt_config({**original.model_dump(), "measurement": "real_model"}))
    bound = bindings.model_copy(update={"protocol_sha256": digest(real)})
    attest_fixture(database, real, bound)
    with sqlite3.connect(database) as db:
        assignment = "assignment-0"
        for event in ("codex_turn", "model_turn_abandoned"):
            db.execute("INSERT INTO agent_turn_reservations(run_id,assignment_id) VALUES (?,?)",
                       (bindings.runs[0].run_id, assignment))
            identity = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            if event == "codex_turn":
                prompt = {"reservation_id": identity, "prefix_sha256": REAL_PROMPT_SHA256,
                          "prompt_sha256": REAL_PROMPT_SHA256, "model": real.model_pin,
                          "runtime": real.runtime_pin}
                db.execute("INSERT INTO agent_job_log(assignment_id,event,detail) VALUES (?,?,?)",
                           (assignment, "heldout_prompt_applied", json.dumps(prompt)))
            db.execute("INSERT INTO agent_job_log(assignment_id,event,detail) VALUES (?,?,?)",
                       (assignment, event, json.dumps({"reservation_id": identity})))
    assert finalize(real, bound, database, expected_sha256=digest(real))["protocol_sha256"] == digest(real)


def test_undeclared_memory_snapshot_is_rejected(tmp_path: Path) -> None:
    database, protocol, bindings = _protocol_fixture(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE heldout_memory_snapshots (run_id TEXT, card_id INTEGER, payload TEXT, digest TEXT)")
        db.execute("INSERT INTO heldout_memory_snapshots VALUES (?,?,?,?)",
                   (bindings.runs[0].run_id, 1, "{}", hashlib.sha256(b"{}").hexdigest()))
    with pytest.raises(ValueError, match="conflicts with arm"):
        finalize(protocol, bindings, database, expected_sha256=digest(protocol))


def test_real_munin_freeze_reconciles_with_protocol(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite"
    session = CodexSession(database)
    scheduler = AgentScheduler(database, FakeHost())
    knowledge = KnowledgeBase(database)

    def manifest(identity: str) -> ChallengeManifest:
        return ChallengeManifest.model_validate({
            "challenge_id": identity, "title": "Independent byte checker",
            "description": "Recover a candidate by static analysis.", "categories": ["rev", "forensics"],
            "scope": {"granted_by": "test", "challenge_id": identity,
                      "allowed_endpoints": [], "authorized": True},
        })

    source = session.start(manifest("practice-source"), evaluation_split="practice")
    card = knowledge.remember(TechniqueCard(
        title="Invert byte checker", category="rev",
        summary="Recover the input by reversing a bytewise checker transform.",
        conditions="A local checker has a reversible byte transform.",
        outcome="inconclusive", source_run_id=source["run_id"], source_split="practice",
    ))
    budget = {"model_calls": 4, "tokens": 100, "actions": 4,
              "seconds": 60.0, "cost_usd": None}
    protocol = Protocol.model_validate({
        "schema_version": 1, "study_id": "real-munin-integration", "measurement": "synthetic_fixture",
        "model_pin": "test-model", "runtime_pin": "fake", "seed": 17,
        "repetitions": 2, "arms": ["full", "without_memory"], "baseline": "full",
        "budgets": {"full": budget, "without_memory": budget},
        "tasks": [{"task_id": f"task{index}", "source_id": f"fixture-{index}",
                   "category": "rev", "difficulty": "easy", "split": "held_out",
                   "exposure": "unknown", "solvability_control_verified": False,
                   "distribution_sha256": f"{index + 10:064x}"} for index in range(2)],
        "arm_config": {
            "full": {"memory_enabled": True, "planner_enabled": True,
                     "max_specialists": 4, "prompt_sha256": "a" * 64},
            "without_memory": {"memory_enabled": False, "planner_enabled": True,
                               "max_specialists": 4, "prompt_sha256": "a" * 64},
        },
        "memory_card_digests": [card["digest"]],
    })
    runs = []
    first_full: str | None = None
    for slot in schedule(protocol):
        target = session.start(manifest(f"{slot['task_id']}-{slot['repetition']}-{slot['arm']}"),
                               evaluation_split="heldout", max_actions=4, wall_seconds=60)
        with pytest.raises(ValueError, match="commitment mismatch"):
            bind_run(protocol, database, target["run_id"], **slot, expected_sha256="0" * 64)
        bind_run(protocol, database, target["run_id"], **slot, expected_sha256=digest(protocol))
        with pytest.raises(ValueError, match="already bound"):
            bind_run(protocol, database, target["run_id"], **slot, expected_sha256=digest(protocol))
        if slot["arm"] == "full":
            first_full = first_full or target["run_id"]
            knowledge.freeze_for_heldout(target["run_id"], [card["id"]])
            assert [item["id"] for item in knowledge.search_for_run(
                target["run_id"], "checker", category="rev")] == [card["id"]]
        else:
            assert knowledge.search_for_run(target["run_id"], "checker", category="rev") == []
        brief = scheduler.brief(target["run_id"], {
            "assignment_id": "wave:triage", "role": "artifact-triage",
            "objective": "Inspect checker", "deliverable": "Bounded findings",
        }, "attempt")
        assert len(brief["prior_knowledge"]) == (1 if slot["arm"] == "full" else 0)
        runs.append({**slot, "run_id": target["run_id"]})
    assert first_full is not None
    scheduler.configure(current_model="test-model", catalog=[])
    wave = AgentLedger(database).create_wave(first_full)
    scheduler.enqueue(first_full, wave["wave_id"])
    started = scheduler.dispatch(first_full)["started"]
    assert started and all(job["model"]["model"] == "test-model" for job in started)
    with pytest.raises(ValueError, match="model or prompt override"):
        run_assignment(scheduler, first_full, started[0]["assignment_id"],
                       started[0]["attempt_id"], object(), model="other-model")  # type: ignore[arg-type]
    with sqlite3.connect(database) as db:
        count = db.execute("SELECT COUNT(*) FROM agent_job_log WHERE event='heldout_arm_applied'").fetchone()[0]
    assert count == len(started)
    real = Protocol.model_validate(real_prompt_config({**protocol.model_dump(), "measurement": "real_model"}))
    extra = session.start(manifest("prompt-binding"), evaluation_split="heldout",
                          max_actions=4, wall_seconds=60)
    slot = schedule(real)[0]
    with pytest.raises(ValueError, match="prompt does not match"):
        bind_run(real, database, extra["run_id"], **slot, expected_sha256=digest(real),
                 prompt_text="changed prompt")
    bind_run(real, database, extra["run_id"], **slot, expected_sha256=digest(real),
             prompt_text=REAL_PROMPT)
    if slot["arm"] == "full":
        knowledge.freeze_for_heldout(extra["run_id"], [card["id"]])
    extra_wave = AgentLedger(database).create_wave(extra["run_id"])
    scheduler.enqueue(extra["run_id"], extra_wave["wave_id"])
    extra_job = scheduler.dispatch(extra["run_id"])["started"][0]
    with pytest.raises(ValueError, match="token cap is not enforceable"):
        run_assignment(scheduler, extra["run_id"], extra_job["assignment_id"],
                       extra_job["attempt_id"], CodexCLI())
    assert scheduler.model_turn_budget(extra["run_id"])["reserved"] == 0

    class OneTurn:
        prompt = ""
        hard_token_budget_enforced = True

        def run(self, prompt, *, model, timeout, should_stop=None, images=None):
            self.prompt = prompt
            return CodexTurn(returncode=0, message=json.dumps({
                "action": "give_up", "intent": None, "report": None,
                "reason": "No bounded path remains for this synthetic checker.",
            }), thread_id="test", usage={"input_tokens": 1, "output_tokens": 1},
                item_types=["agent_message"])

    runner = OneTurn()
    run_assignment(scheduler, extra["run_id"], extra_job["assignment_id"],
                   extra_job["attempt_id"], runner)  # type: ignore[arg-type]
    assert runner.prompt.startswith(REAL_PROMPT + "\n\n")
    with sqlite3.connect(database) as db:
        prompts = db.execute("SELECT detail FROM agent_job_log WHERE assignment_id=? "
                             "AND event='heldout_prompt_applied'", (extra_job["assignment_id"],)).fetchall()
    assert prompts and json.loads(prompts[0][0])["prefix_sha256"] == REAL_PROMPT_SHA256
    bindings = Bindings.model_validate({"protocol_sha256": digest(protocol), "runs": runs})
    result = finalize(protocol, bindings, database, expected_sha256=digest(protocol))
    assert result["ledger_reconciliation"]["trials_reconciled"] == 8


def test_protocol_real_model_aggregate_cap(tmp_path: Path) -> None:
    _, protocol, _ = _protocol_fixture(tmp_path)
    data = protocol.model_dump()
    data["measurement"] = "real_model"
    data["budgets"]["full"]["model_calls"] = 7
    data["budgets"]["single_agent"]["model_calls"] = 7
    with pytest.raises(ValueError, match="call or time cap"):
        Protocol.model_validate(data)


def test_protocol_rejects_observed_call_overrun(tmp_path: Path) -> None:
    database, protocol, bindings = _protocol_fixture(tmp_path)
    data = protocol.model_dump()
    data["measurement"] = "real_model"
    real_protocol = Protocol.model_validate(real_prompt_config(data))
    real_bindings = bindings.model_copy(update={"protocol_sha256": digest(real_protocol)})
    with sqlite3.connect(database) as db:
        db.executemany("INSERT INTO agent_turn_reservations(run_id,assignment_id) VALUES (?,?)",
                       [(bindings.runs[0].run_id, "assignment-0")] * 50)
    attest_fixture(database, real_protocol, real_bindings)
    with sqlite3.connect(database) as db:
        identities = [row[0] for row in db.execute("SELECT rowid FROM agent_turn_reservations "
                                                   "WHERE assignment_id='assignment-0'")]
        for identity in identities[1:]:
            db.execute("INSERT INTO agent_job_log(assignment_id,event,detail) VALUES (?,?,?)",
                       ("assignment-0", "heldout_prompt_applied",
                        json.dumps({"reservation_id": identity, "prefix_sha256": REAL_PROMPT_SHA256,
                                    "prompt_sha256": REAL_PROMPT_SHA256, "model": real_protocol.model_pin,
                                    "runtime": real_protocol.runtime_pin})))
            db.execute("INSERT INTO agent_job_log(assignment_id,event,detail) VALUES (?,?,?)",
                       ("assignment-0", "codex_turn", json.dumps({"reservation_id": identity})))
    with pytest.raises(ValueError, match="observed real-model"):
        finalize(real_protocol, real_bindings, database, expected_sha256=digest(real_protocol))


def test_protocol_rejects_corrupt_ledger(tmp_path: Path) -> None:
    database, protocol, bindings = _protocol_fixture(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE events SET digest='corrupt' WHERE run_id=? AND sequence=1",
                   (bindings.runs[0].run_id,))
    with pytest.raises(ValueError, match="event chain"):
        finalize(protocol, bindings, database, expected_sha256=digest(protocol))


def test_protocol_cli_prepare_and_finalize_fail_closed(tmp_path: Path, monkeypatch, capsys) -> None:
    database, protocol, bindings = _protocol_fixture(tmp_path)
    design = tmp_path / "protocol.json"
    run_map = tmp_path / "bindings.json"
    design.write_text(protocol.model_dump_json())
    run_map.write_text(bindings.model_dump_json())
    monkeypatch.setattr(sys, "argv", ["heldout-protocol", "prepare", str(design)])
    assert main() == 0
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["protocol_sha256"] == digest(protocol)
    assert len(prepared["schedule"]) == 8
    args = ["heldout-protocol", "finalize", str(design), str(run_map),
            "--database", str(database), "--expected-sha256", digest(protocol)]
    monkeypatch.setattr(sys, "argv", args)
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["ledger_reconciliation"]["trials_reconciled"] == 8
    monkeypatch.setattr(sys, "argv", args[:-1] + ["0" * 64])
    assert main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "held-out protocol rejected\n"
