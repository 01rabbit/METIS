"""Paired Issue #6 scheduler benchmark with a protected synthetic oracle.

This measures simulated provider-turn rounds, not model reasoning or wall-clock
latency. All decoding, evidence recording, budget reservations, and synthesis go
through the production controller interfaces.
"""
import base64
import hashlib
import json
import random
import sqlite3
import stat
from pathlib import Path
from typing import Any

from metis.core.agent_host import FakeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.ctf_orchestration import AgentLedger
from metis.core.verification import FixtureOracle


def _benchmark_wave(ledger: AgentLedger, run_id: str, arm: str) -> dict[str, Any]:
    """Create test-only one-agent or two-specialist plans with identical inputs."""
    plan = ledger.create_wave(run_id, mode="delegated")
    by_role = {item["role"]: item for item in plan["assignments"]}
    all_artifacts = list(ledger.session.context(run_id)["challenge"]["artifacts"])
    if arm == "single":
        assignments = [dict(by_role["crypto-specialist"])]
        assignments[0]["inputs"] = {"artifacts": all_artifacts}
        assignments[0]["objective"] = "Decode both registered components sequentially."
        assignments[0]["max_turns"] = 2
    elif arm == "multi":
        assignments = [dict(by_role["crypto-specialist"]), dict(by_role["forensics-specialist"])]
        for index, assignment in enumerate(assignments):
            assignment["inputs"] = {"artifacts": [all_artifacts[index]]}
            assignment["objective"] = f"Decode assigned component {index + 1}."
            assignment["max_turns"] = 1
    else:
        raise ValueError("unknown benchmark arm")
    plan["assignments"] = assignments
    plan["decision"]["required_roles"] = [item["role"] for item in assignments]
    plan["daybreak_covers"] = []
    with sqlite3.connect(ledger.database) as db:
        db.execute("UPDATE ctf_agent_waves SET plan=? WHERE wave_id=?",
                   (json.dumps(plan, sort_keys=True), plan["wave_id"]))
    return plan


def _run_arm(scheduler: AgentScheduler, run_id: str, arm: str) -> dict[str, Any]:
    plan = _benchmark_wave(scheduler.ledger, run_id, arm)
    jobs = scheduler.enqueue(run_id, plan["wave_id"])
    started = scheduler.dispatch(run_id)
    assert len(started["started"]) == len(jobs) == len(plan["assignments"])
    assigned = {item["assignment_id"]: item for item in plan["assignments"]}
    decoded: dict[str, bytes] = {}
    evidence: dict[str, list[int]] = {identity: [] for identity in assigned}
    max_rounds = max(len(item["inputs"]["artifacts"]) for item in assigned.values())
    observed_poll_states: dict[str, str] = {}
    original_poll = scheduler.host.poll

    def record_poll(job_id: str, *, timeout: float = 5.0) -> dict[str, Any]:
        result = original_poll(job_id, timeout=timeout)
        observed_poll_states[job_id] = result["state"]
        return result

    scheduler.host.poll = record_poll  # type: ignore[method-assign]

    try:
        for provider_round in range(1, max_rounds + 1):
            scheduler.tick()
            for attempt in started["started"]:
                host_job = scheduler.host.jobs[attempt["host_job_id"]]
                assert host_job["polls"] == provider_round
                expected_state = "finished" if provider_round >= host_job["plan"]["after"] else "running"
                assert observed_poll_states[attempt["host_job_id"]] == expected_state
            for attempt in started["started"]:
                assignment_id = attempt["assignment_id"]
                artifacts = assigned[assignment_id]["inputs"]["artifacts"]
                if provider_round > len(artifacts):
                    continue
                reservation = scheduler.reserve_model_turn(run_id, assignment_id, attempt["attempt_id"])
                assert reservation is not None
                artifact = artifacts[provider_round - 1]
                suffix = Path(artifact).suffix
                tool = "base64_decode" if suffix == ".b64" else "hex_decode"
                observed = scheduler.intent(run_id, assignment_id, attempt["attempt_id"], {
                    "kind": "artifact", "tool": tool, "artifact": artifact,
                })
                result = observed["observation"]
                assert result["ok"] is True
                component = base64.b64decode(result["result"]["base64"], validate=True)
                decoded[artifact] = component
                evidence[assignment_id].append(observed["evidence_sequence"])
                if provider_round == len(artifacts):
                    report = {
                        "hypothesis": "The declared encoded component contains one candidate fragment.",
                        "evidence": f"A bounded decoder returned {len(component)} bytes at event "
                                   f"{observed['evidence_sequence']}.",
                        "falsifier": "A strict decoder rejection would refute this representation.",
                        "next_action": f"Combine the decoded fragment from {artifact} with its paired fragment.",
                        "event_sequences": evidence[assignment_id],
                        "artifact_refs": artifacts,
                        "status": "supported",
                    }
                    scheduler.complete(run_id, assignment_id, attempt["attempt_id"], report)
    finally:
        scheduler.host.poll = original_poll  # type: ignore[method-assign]

    synthesis = scheduler.ledger.synthesize(run_id, plan["wave_id"])
    assert synthesis["complete"] is True
    assert synthesis["decision"]["ready_for_synthesis"] is True
    context = scheduler.session.context(run_id)
    assert context["actions_remaining"] == 2
    assert scheduler.model_turn_budget(run_id) == {"limit": 2, "reserved": 2, "remaining": 0}
    with sqlite3.connect(scheduler.database) as db:
        tool_actions = db.execute("SELECT COUNT(*) FROM agent_actions WHERE run_id=?", (run_id,)).fetchone()[0]
        turns = db.execute("SELECT COUNT(*) FROM agent_turn_reservations WHERE run_id=?", (run_id,)).fetchone()[0]
    assert tool_actions == 2 and turns == 2
    return {"ticks": max_rounds, "decoded": decoded, "synthesis": synthesis}


def test_issue6_paired_synthetic_scheduler_benchmark_uses_matched_budgets(tmp_path):
    seed = 20261117
    rng = random.Random(seed)
    database = tmp_path / "state.sqlite"
    host = FakeHost(script={
        role: lambda assignment, _brief: {
            "after": len(assignment["inputs"]["artifacts"]), "state": "finished", "output": None,
        }
        for role in ("crypto-specialist", "forensics-specialist")
    }, max_parallel=2)
    scheduler = AgentScheduler(database, host)
    scheduler.configure(global_slots=2, per_run_slots=2, specialist_turn_budget=2)

    cases: list[dict[str, Any]] = []
    roots: list[Path] = []
    oracle_values: dict[str, str] = {}
    for index in range(30):
        case_id = f"paired-{index:02d}"
        left = b"left:" + rng.randbytes(16)
        right = b"right:" + rng.randbytes(16)
        encodings = ["b64", "hex"] if index % 2 == 0 else ["hex", "b64"]
        parts = [left, right]
        sources = []
        for part_index, (part, encoding) in enumerate(zip(parts, encodings, strict=True)):
            source = tmp_path / f"{case_id}-{part_index}.{encoding}"
            source.write_text(base64.b64encode(part).decode() if encoding == "b64" else part.hex())
            sources.append(source)
        run_ids = {}
        for arm in ("single", "multi"):
            result = scheduler.session.intake(
                title=f"Synthetic paired scheduler {case_id}", description="Decode two independent fragments.",
                paths=sources, categories=["crypto", "forensics"], max_actions=4, wall_seconds=300,
            )
            run_ids[arm] = result["run_id"]
            root = scheduler.session.artifact_root(result["run_id"])
            assert root is not None
            roots.append(root)
        answer = hashlib.sha256(left + b"\0" + right).hexdigest()
        oracle_values[case_id] = answer
        cases.append({"case_id": case_id, "run_ids": run_ids, "private_fragments": (left, right)})

    oracle_path = tmp_path / "protected-oracle.json"
    oracle_path.write_text(json.dumps(oracle_values, sort_keys=True))
    oracle_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    oracle = FixtureOracle(oracle_path, solver_roots=tuple(roots))

    paired_results = []
    for case in cases:
        run_outputs = {}
        arms = ("multi", "single") if int(case["case_id"].split("-")[-1]) % 2 else ("single", "multi")
        for arm in arms:
            output = _run_arm(scheduler, case["run_ids"][arm], arm)
            ordered_artifacts = scheduler.session.context(case["run_ids"][arm])["challenge"]["artifacts"]
            candidate = hashlib.sha256(
                output["decoded"][ordered_artifacts[0]] + b"\0" + output["decoded"][ordered_artifacts[1]]
            ).hexdigest()
            run_outputs[arm] = {
                "ticks": output["ticks"],
                "verified": oracle.verify(case["case_id"], candidate),
                "synthesis": output["synthesis"],
                "candidate": candidate,
                "run_id": case["run_ids"][arm],
            }
        paired_results.append(run_outputs)

    assert all(pair["single"]["verified"] and pair["multi"]["verified"] for pair in paired_results)
    assert all(pair["single"]["ticks"] == 2 and pair["multi"]["ticks"] == 1 for pair in paired_results)
    assert all(pair["single"]["synthesis"]["complete"] and pair["multi"]["synthesis"]["complete"]
               for pair in paired_results)
    assert sum(pair["single"]["ticks"] for pair in paired_results) == 60
    assert sum(pair["multi"]["ticks"] for pair in paired_results) == 30

    for case, pair in zip(cases, paired_results, strict=True):
        for arm_result in pair.values():
            run_id = arm_result["run_id"]
            events = scheduler.session.store.read(run_id)
            reports = arm_result["synthesis"]["reports"]
            persisted = json.dumps([event.model_dump() for event in events]) + json.dumps(reports)
            assert arm_result["candidate"] not in persisted
            assert str(oracle_path) not in persisted
            for fragment in case["private_fragments"]:
                assert fragment.hex() not in persisted
                assert base64.b64encode(fragment).decode() not in persisted

