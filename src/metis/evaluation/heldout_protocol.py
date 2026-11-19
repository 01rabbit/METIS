"""Freeze a paired benchmark design before runs and reconcile its bound evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from metis.evaluation.heldout_analysis import (
    Arm,
    Budget,
    Identifier,
    Record,
    Task,
    analyze,
    reconcile_evidence,
)
from metis.evaluation.heldout_study_export import ExportManifest, RunAssignment, export

MAX_PROTOCOL_BYTES = 1_000_000
MAX_BINDINGS_BYTES = 1_000_000
MAX_SLOTS = 2_000


class ProtocolTask(Task):
    source_id: Identifier
    distribution_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ArmConfig(Record):
    memory_enabled: bool
    planner_enabled: bool
    max_specialists: Annotated[int, Field(ge=1, le=4)]
    prompt_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Protocol(Record):
    schema_version: int = Field(ge=1, le=1)
    study_id: Identifier
    measurement: Literal["synthetic_fixture", "real_model"]
    model_pin: Identifier
    runtime_pin: Identifier
    seed: Annotated[int, Field(ge=0, le=2**32 - 1)]
    repetitions: Annotated[int, Field(ge=2, le=20)]
    arms: Annotated[list[Arm], Field(min_length=2, max_length=4)]
    baseline: Arm
    budgets: dict[Arm, Budget]
    tasks: Annotated[list[ProtocolTask], Field(min_length=2, max_length=1000)]
    arm_config: dict[Arm, ArmConfig]
    memory_card_digests: Annotated[list[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]],
                                   Field(max_length=20)] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_design(self) -> Protocol:
        if len(set(self.arms)) != len(self.arms) or self.baseline not in self.arms:
            raise ValueError("invalid arms")
        if set(self.budgets) != set(self.arms) or any(
            budget != self.budgets[self.baseline] for budget in self.budgets.values()
        ):
            raise ValueError("unequal arm budgets")
        if set(self.arm_config) != set(self.arms):
            raise ValueError("missing arm configuration")
        if len(set(self.memory_card_digests)) != len(self.memory_card_digests):
            raise ValueError("duplicate memory card digest")
        if self.measurement == "real_model" and "without_memory" in self.arms and not self.memory_card_digests:
            raise ValueError("memory ablation requires frozen prior cards")
        for arm, config in self.arm_config.items():
            expected = {
                "full": (True, True, False),
                "without_memory": (False, True, False),
                "without_planner": (True, False, False),
                "single_agent": (True, True, True),
            }[arm]
            if (config.memory_enabled, config.planner_enabled,
                    config.max_specialists == 1) != expected:
                raise ValueError("arm configuration conflicts with its label")
        if len({task.task_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("duplicate task")
        slots = len(self.tasks) * self.repetitions * len(self.arms)
        if slots > MAX_SLOTS:
            raise ValueError("benchmark schedule exceeds slot limit")
        if self.measurement == "real_model":
            budget = self.budgets[self.baseline]
            if slots * budget.model_calls > 50 or slots * budget.seconds > 7_200:
                raise ValueError("real-model study exceeds the authorized call or time cap")
        return self


class Bindings(Record):
    protocol_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    runs: Annotated[list[RunAssignment], Field(min_length=8, max_length=MAX_SLOTS)]


def digest(protocol: Protocol) -> str:
    """Hash the fully validated, canonical design without run IDs or answers."""
    protocol = Protocol.model_validate(protocol.model_dump())
    canonical = json.dumps(protocol.model_dump(mode="json"), sort_keys=True,
                           separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def schedule(protocol: Protocol) -> list[dict[str, Any]]:
    """Produce a reproducible balanced arm order within each task repetition."""
    protocol = Protocol.model_validate(protocol.model_dump())
    slots: list[dict[str, Any]] = []
    for task in sorted(protocol.tasks, key=lambda item: item.task_id):
        for repetition in range(protocol.repetitions):
            arms = sorted(protocol.arms, key=lambda arm: hashlib.sha256(
                f"{protocol.seed}:{task.task_id}:{repetition}:{arm}".encode()).digest())
            for arm in arms:
                slots.append({"task_id": task.task_id, "repetition": repetition, "arm": arm})
    return slots


def reconcile_memory_snapshots(protocol: Protocol, bindings: Bindings, database: Path) -> None:
    """Require each bound run's frozen cards to match the committed arm treatment."""
    if not protocol.memory_card_digests:
        return
    expected = sorted(protocol.memory_card_digests)
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='heldout_memory_snapshots'").fetchone() is None:
            raise ValueError("held-out memory snapshots missing")
        db.execute("BEGIN")
        for assignment in bindings.runs:
            rows = db.execute(
                "SELECT card_id,payload,digest FROM heldout_memory_snapshots WHERE run_id=? ORDER BY digest",
                (assignment.run_id,),
            ).fetchall()
            if any(hashlib.sha256(payload.encode()).hexdigest() != card_digest
                   for _, payload, card_digest in rows):
                raise ValueError("held-out memory snapshot digest mismatch")
            actual = [card_digest for _, _, card_digest in rows]
            if actual != (expected if protocol.arm_config[assignment.arm].memory_enabled else []):
                raise ValueError("held-out memory snapshot conflicts with arm")
            for card_id, payload, card_digest in rows:
                source = db.execute(
                    "SELECT payload,digest,source_split,created FROM munin_cards WHERE id=?",
                    (card_id,),
                ).fetchone()
                run = db.execute("SELECT started FROM codex_sessions WHERE run_id=?",
                                 (assignment.run_id,)).fetchone()
                if (source is None or run is None or source[:2] != (payload, card_digest)
                        or source[2] not in {"practice", "competition"} or source[3] > run[0]):
                    raise ValueError("held-out memory snapshot lacks prior source")


def finalize(protocol: Protocol, bindings: Bindings, database: Path,
             *, expected_sha256: str) -> dict[str, Any]:
    """Accept only the frozen protocol and exact run matrix, then analyze ledger evidence."""
    protocol = Protocol.model_validate(protocol.model_dump())
    bindings = Bindings.model_validate(bindings.model_dump())
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("invalid protocol commitment")
    actual = digest(protocol)
    if actual != expected_sha256 or bindings.protocol_sha256 != actual:
        raise ValueError("protocol commitment mismatch")
    planned = [(slot["task_id"], slot["repetition"], slot["arm"])
               for slot in schedule(protocol)]
    bound = [(run.task_id, run.repetition, run.arm) for run in bindings.runs]
    if bound != planned:
        raise ValueError("run bindings do not follow the frozen schedule")
    reconcile_memory_snapshots(protocol, bindings, database)
    data = protocol.model_dump()
    data.pop("arm_config")
    data.pop("memory_card_digests")
    data["tasks"] = [task.model_dump(exclude={"source_id", "distribution_sha256"})
                     for task in protocol.tasks]
    data["runs"] = [run.model_dump() for run in bindings.runs]
    manifest = ExportManifest.model_validate(data)
    study = export(manifest, database)
    if protocol.measurement == "real_model" and (
        sum(trial.model_calls for trial in study.trials) > 50
        or sum(trial.seconds for trial in study.trials) > 7_200
    ):
        raise ValueError("observed real-model study exceeds the authorized cap")
    return {"protocol_sha256": actual, "study": study.model_dump(mode="json"),
            "analysis": analyze(study),
            "ledger_reconciliation": reconcile_evidence(study, database)}


def _read(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("input file unavailable")
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("input file exceeds limit")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze and reconcile a held-out benchmark protocol")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("protocol", type=Path)
    finish = commands.add_parser("finalize")
    finish.add_argument("protocol", type=Path)
    finish.add_argument("bindings", type=Path)
    finish.add_argument("--database", type=Path, required=True)
    finish.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    try:
        protocol = Protocol.model_validate_json(_read(args.protocol, MAX_PROTOCOL_BYTES))
        if args.command == "prepare":
            output = {"protocol_sha256": digest(protocol), "schedule": schedule(protocol)}
        else:
            bindings = Bindings.model_validate_json(_read(args.bindings, MAX_BINDINGS_BYTES))
            output = finalize(protocol, bindings, args.database,
                              expected_sha256=args.expected_sha256)
    except (OSError, ValueError, TypeError, sqlite3.Error):
        print("held-out protocol rejected", file=sys.stderr)
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
