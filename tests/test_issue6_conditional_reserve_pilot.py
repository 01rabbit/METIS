"""Frozen shape, outcome, and finalization checks for conditional delegation."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

from metis.evaluation.issue6_conditional_reserve_pilot import ARMS, ORDER_SEED, analyze

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_issue6_conditional_reserve_pilot as runner
import run_issue6_handoff_diagnostic as diagnostic

from metis.core.agent_host import BridgeHost
from metis.core.agent_scheduler import AgentScheduler
from metis.core.codex_session import CodexSession


def _fixture() -> tuple[dict, dict[str, list[str]], dict[str, list[str]]]:
    families = {f"reserve12-{index:02d}": list(pair)
                for index, pair in enumerate(family for family in runner.FAMILIES for _ in range(2))}
    rng = random.Random(ORDER_SEED)
    order = {}
    records = []
    for task_id in families:
        case = f"{task_id}-rep-0"
        arms = list(ARMS)
        rng.shuffle(arms)
        order[case] = arms
        for arm in arms:
            verified = arm == "single" or task_id.endswith("00")
            records.append({
                "case": case, "task_id": task_id, "arm": arm,
                "oracle_verified": verified, "workflow_verified": verified,
                "verified_assignment_state": "completed" if verified else None,
                "fallback_dispatched": arm == "conditional", "job_states": (
                    ["failed", "completed"] if arm == "conditional" else ["completed"]),
                "model": "gpt-6.1-sol", "cli": "0.169.0", "reasoning_effort": "low",
                "actions": 2, "calls_observed": 4, "calls_reserved": 4,
                "elapsed_seconds": 1.0, "usage": {}, "usage_complete": False,
                "synthesis_complete": True, "candidate_ready_jobs": int(verified),
                "decision_counts": {}, "report_rejections": 0,
                "report_rejection_categories": {}, "report_rejection_stages": {},
                "terminal_reason_categories": {}, "model_turn_budget_denials": 0,
                "peer_reserve_denials": 0, "cost_usd": "unknown", "run_id": "redacted",
            })
    return runner._dataset(records, families, order), families, order


def test_conditional_pilot_analyzes_complete_pairs_and_finalizes(tmp_path: Path) -> None:
    data, families, order = _fixture()
    result = analyze(data)
    assert result["workflow_verified"] == {"single": 12, "conditional": 1}
    assert result["raw_oracle_verified"] == {"single": 12, "conditional": 1}
    assert result["mean_actions"] == {"single": 2, "conditional": 2}
    assert result["conditional_minus_single"] == -0.9167
    assert result["primary_positive"] is False
    output = tmp_path / "final.json"
    with pytest.raises(ValueError, match="24 unique"):
        runner._finalize(data["records"][:-1], families, order, output)
    assert not output.exists()
    runner._finalize(data["records"], families, order, output)
    assert analyze(json.loads(output.read_text(encoding="utf-8"))) == result


def test_conditional_pilot_rejects_duplicate_and_fabricated_success() -> None:
    data, _, _ = _fixture()
    data["records"][0] = dict(data["records"][1])
    with pytest.raises(ValueError, match="24 unique"):
        analyze(data)
    data, _, _ = _fixture()
    conditional = next(row for row in data["records"] if row["arm"] == "conditional"
                       and not row["workflow_verified"])
    conditional["workflow_verified"] = True
    with pytest.raises(ValueError, match="inconsistent"):
        analyze(data)


def test_committed_conditional_trial_matches_committed_analysis() -> None:
    directory = ROOT / "docs/reports/data"
    data = json.loads((directory / "issue6-conditional-reserve-pilot-2026-11-18.json").read_text(
        encoding="utf-8"))
    expected = json.loads((directory / "issue6-conditional-reserve-pilot-analysis-2026-11-18.json").read_text(
        encoding="utf-8"))
    result = analyze(data)
    assert result == expected
    assert result["workflow_verified"] == {"single": 12, "conditional": 11}
    assert result["conditional_minus_single"] == -0.0833
    assert result["fallback_dispatched"] == 2


def test_conditional_fallback_uses_second_wave_and_remaining_budget(tmp_path: Path) -> None:
    artifacts = [tmp_path / f"component-{index}.txt" for index in range(2)]
    for path in artifacts:
        path.write_text("dGVzdA==", encoding="ascii")
    session = CodexSession(tmp_path / "state.sqlite")
    run_id = session.intake(title="conditional fixture", description="Decode two components",
                            paths=artifacts, categories=["crypto", "forensics"],
                            max_actions=4, wall_seconds=600,
                            evaluation_split="practice")["run_id"]
    scheduler = AgentScheduler(session.database, BridgeHost(max_parallel=2))
    scheduler.configure(global_slots=2, per_run_slots=2, specialist_turn_budget=8,
                        catalog=[{"id": diagnostic.MODEL, "tier": "standard"}],
                        current_model=diagnostic.MODEL, memory_retrieval=False)
    lead = diagnostic.make_plan(scheduler.ledger, run_id, "conditional")
    scheduler.enqueue(run_id, lead["plan"]["wave_id"])
    started = scheduler.dispatch(run_id)["started"]
    assert len(started) == 1
    assert scheduler.jobs(run_id, lead["plan"]["wave_id"])[0]["max_turns"] == 2
    for artifact in lead["artifacts"]:
        scheduler.intent(run_id, started[0]["assignment_id"], started[0]["attempt_id"],
                         {"kind": "artifact", "tool": "text", "artifact": artifact})
    assert session.context(run_id)["actions_remaining"] == 2
    scheduler.fail(started[0]["assignment_id"], started[0]["attempt_id"], "no candidate")
    assert scheduler.ledger.synthesize(run_id, lead["plan"]["wave_id"])["decision"]["ready_for_synthesis"]
    fallback = diagnostic.make_conditional_fallback(scheduler.ledger, run_id, lead["artifacts"])
    scheduler.enqueue(run_id, fallback["plan"]["wave_id"])
    second = scheduler.dispatch(run_id)["started"]
    assert len(second) == 1
    fallback_job = scheduler.jobs(run_id, fallback["plan"]["wave_id"])[0]
    assert fallback_job["role"] == "forensics-specialist"
    assert fallback_job["max_turns"] == 2
    assert scheduler.brief(run_id, fallback["plan"]["assignments"][0],
                           second[0]["attempt_id"])["artifacts"] == lead["artifacts"]
