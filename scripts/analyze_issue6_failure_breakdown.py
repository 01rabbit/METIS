"""Retrospective, answer-free failure breakdown of the Issue #6 symmetric replication.

Reads only the retained JSON dataset and prints JSON. Exploratory; makes no gain claim.
Per-job failure categories, per-specialist call counts and report-rejection counts are NOT
retained, so the budget-split hypothesis is tested only through clearly labelled proxies.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs/reports/data/issue6-symmetric-replication-2026-11-18.json"
PER_SPECIALIST_CAP = 4
TOTAL_CAP = 8
MISSING_FIELDS = [
    "failure_category / specialist_outcomes (added in PRs #135/#140, after this run)",
    "per-job calls_used (only the per-run total is retained)",
    "report-rejection count", "timeout flag", "host-error flag", "per-job stop reason",
]


def _key(states: list[str]) -> str:
    return "+".join(sorted(states))


def analyze(data: dict[str, Any]) -> dict[str, Any]:
    records = data["records"]
    out: dict[str, Any] = {"study": data["study"], "missing_fields": MISSING_FIELDS, "arms": {}}
    for arm in ("single", "multi"):
        rs = [r for r in records if r["arm"] == arm]
        out["arms"][arm] = {
            "n": len(rs),
            "workflow_complete": sum(r["synthesis_complete"] for r in rs),
            "oracle_verified": sum(r["oracle_verified"] for r in rs),
            "verified_and_complete": sum(r["oracle_verified"] and r["synthesis_complete"] for r in rs),
            "job_state_pattern": dict(sorted(Counter(_key(r["job_states"]) for r in rs).items())),
            "calls_observed": dict(sorted(Counter(r["calls_observed"] for r in rs).items())),
            "calls_reserved": dict(sorted(Counter(r["calls_reserved"] for r in rs).items())),
            "actions": dict(sorted(Counter(r["actions"] for r in rs).items())),
            "mean_calls": sum(r["calls_observed"] for r in rs) / len(rs),
            "mean_elapsed_seconds": round(sum(r["elapsed_seconds"] for r in rs) / len(rs), 3),
        }
    single = [r for r in records if r["arm"] == "single"]
    multi = [r for r in records if r["arm"] == "multi"]
    failed_multi = [r for r in multi if "failed" in r["job_states"]]
    jobs = Counter(s for r in multi for s in r["job_states"])
    out["multi_jobs"] = {"total": sum(jobs.values()), **dict(sorted(jobs.items()))}
    out["multi_failed_trials"] = {
        "n": len(failed_multi),
        "at_total_call_cap_PROXY": sum(r["calls_observed"] >= TOTAL_CAP for r in failed_multi),
        "oracle_verified_despite_failed_job": sum(r["oracle_verified"] for r in failed_multi),
        "oracle_not_verified": sum(not r["oracle_verified"] for r in failed_multi),
        "all_actions_used": sum(r["actions"] == 4 for r in failed_multi),
    }
    out["budget_split_proxy"] = {
        "per_specialist_cap": PER_SPECIALIST_CAP,
        "single_runs": len(single),
        "single_runs_using_more_than_per_specialist_cap": sum(
            r["calls_observed"] > PER_SPECIALIST_CAP for r in single),
        "single_verified_runs_over_cap": sum(
            r["calls_observed"] > PER_SPECIALIST_CAP for r in single if r["oracle_verified"]),
        "multi_runs": len(multi),
        "multi_runs_at_total_cap": sum(r["calls_observed"] >= TOTAL_CAP for r in multi),
        "multi_complete_runs_at_total_cap": sum(
            r["calls_observed"] >= TOTAL_CAP for r in multi if r["synthesis_complete"]),
        "note": "total calls always equal the cap in multi, so the total cannot localise which "
                "specialist exhausted its 4-call share",
    }
    return out


def main() -> None:
    print(json.dumps(analyze(json.loads(DATA.read_text(encoding="utf-8"))), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
