"""Freeze a paired benchmark design before runs and reconcile its bound evidence."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, model_validator

from metis.core.ctf_knowledge import validate_heldout_snapshot_source
from metis.core.study_token_admission import TokenLaunchOutcome
from metis.core.token_reservation import FULL_CONTEXT_RESERVATION_TOKENS
from metis.evaluation.heldout_analysis import (
    Arm,
    Budget,
    Identifier,
    Record,
    Task,
    _analyze_with_verified_controls,
    analyze,
    reconcile_evidence,
)
from metis.evaluation.heldout_arm import bind, binding
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


class LlamaBackendPin(Record):
    binary_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    model_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    native_manifest_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    database_path: str
    budget_key: Identifier
    token_limit: Annotated[int, Field(ge=1, le=10_000_000)]
    max_output_tokens: Annotated[int, Field(ge=1, le=4096)]
    context_reservation: Literal[True]

    @model_validator(mode="after")
    def valid_database(self) -> LlamaBackendPin:
        path = Path(self.database_path)
        if not path.is_absolute() or str(path.resolve()) != self.database_path:
            raise ValueError("llama database path must be canonical and absolute")
        return self


class Protocol(Record):
    schema_version: int = Field(ge=1, le=1)
    study_id: Identifier
    measurement: Literal["synthetic_fixture", "real_model"]
    model_pin: Identifier
    runtime_pin: Identifier
    control_reviewer_key_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    llama_backend: LlamaBackendPin | None = None
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
        if self.llama_backend is not None and (
            self.measurement != "real_model" or self.llama_backend.token_limit >
            slots * self.budgets[self.baseline].tokens
        ):
            raise ValueError("llama shared cap exceeds declared study token budget")
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
    payload = protocol.model_dump(mode="json")
    # Preserve the v1 digest for existing llama pins that predate the optional
    # native manifest field. A present manifest is included in the commitment.
    if protocol.llama_backend is not None and protocol.llama_backend.native_manifest_sha256 is None:
        payload["llama_backend"].pop("native_manifest_sha256", None)
    # Existing v1 protocols had no reviewer-key field; keep their commitments
    # stable while pinning the key whenever acceptance review is preregistered.
    if protocol.control_reviewer_key_sha256 is None:
        payload.pop("control_reviewer_key_sha256", None)
    canonical = json.dumps(payload, sort_keys=True,
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


def bind_run(protocol: Protocol, database: Path, run_id: str, *, task_id: str,
             repetition: int, arm: Arm, expected_sha256: str,
             prompt_text: str | None = None) -> None:
    """Bind a scheduled run to its exact prospective treatment before work."""
    if not re.fullmatch(r"[0-9a-f]{32}", run_id) or digest(protocol) != expected_sha256:
        raise ValueError("held-out protocol commitment mismatch")
    slot = {"task_id": task_id, "repetition": repetition, "arm": arm}
    if slot not in schedule(protocol):
        raise ValueError("run is outside held-out schedule")
    bind(database, run_id, {"protocol_sha256": expected_sha256, **slot,
                            "study_id": protocol.study_id,
                            "measurement": protocol.measurement,
                            "arm_config": protocol.arm_config[arm].model_dump(mode="json"),
                            "memory_card_digests": protocol.memory_card_digests,
                            "model_pin": protocol.model_pin, "runtime_pin": protocol.runtime_pin,
                            "llama_backend": (protocol.llama_backend.model_dump(mode="json", exclude_none=True)
                                              if protocol.llama_backend is not None else None),
                            "budget": protocol.budgets[arm].model_dump(mode="json"),
                            "prompt_text": prompt_text})


def reconcile_memory_snapshots(protocol: Protocol, bindings: Bindings, database: Path) -> None:
    """Require each bound run's frozen cards to match the committed arm treatment."""
    expected = sorted(protocol.memory_card_digests)
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='heldout_memory_snapshots'").fetchone() is None:
            if expected:
                raise ValueError("held-out memory snapshots missing")
            return
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
                validate_heldout_snapshot_source(db, assignment.run_id, card_id, payload, card_digest)


def _native_dispatch_matches(
    db: sqlite3.Connection, protocol: Protocol, slot: RunAssignment, *,
    protocol_sha256: str, assignment_id: str, attempt_id: str, reservation_id: int,
    prompt_sha256: str, abandoned: bool,
) -> bool:
    """Match a scheduler reservation to one non-fixture native observation."""
    backend = protocol.llama_backend
    if backend is None or backend.native_manifest_sha256 is None:
        return False
    try:
        receipts = db.execute(
            "SELECT p.protocol_sha256,p.runtime_sha256,p.model_sha256,p.token_limit,"
            "p.native_manifest_sha256,s.task_id,s.repetition,s.arm,s.token_limit,"
            "a.assignment_id,a.attempt_id,a.prompt_sha256,a.tokens,"
            "l.nonce,l.consumed,l.launched,o.nonce,o.status,o.exit_status,"
            "o.observed_work,o.native_manifest_sha256 "
            "FROM study_token_launches l "
            "JOIN study_token_attempts a USING (run_id,turn_reservation_id) "
            "JOIN study_token_slots s USING (study_id,run_id) "
            "JOIN study_token_pins p USING (study_id) "
            "LEFT JOIN study_token_outcomes o ON o.nonce=l.nonce "
            "WHERE l.run_id=? AND l.turn_reservation_id=? AND p.study_id=? "
            "AND NOT EXISTS (SELECT 1 FROM study_token_fixture_claims f WHERE f.nonce=l.nonce) "
            "LIMIT 2",
            (slot.run_id, reservation_id, protocol.study_id),
        ).fetchall()
    except sqlite3.OperationalError:
        return False
    if len(receipts) != 1:
        return False
    *receipt, nonce, consumed, launched, outcome_nonce, status, exit_status, observed_work, manifest = receipts[0]
    reserved_tokens = FULL_CONTEXT_RESERVATION_TOKENS + backend.max_output_tokens
    if tuple(receipt) != (
        protocol_sha256, backend.binary_sha256, backend.model_sha256, backend.token_limit,
        backend.native_manifest_sha256, slot.task_id, slot.repetition, slot.arm,
        protocol.budgets[slot.arm].tokens, assignment_id, attempt_id, prompt_sha256, reserved_tokens,
    ) or not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
        return False
    if abandoned:
        return (consumed, launched, outcome_nonce) == (0, 0, None)
    if (consumed, launched, outcome_nonce) != (1, 1, nonce):
        return False
    try:
        outcome = TokenLaunchOutcome.model_validate({
            "status": status,
            "exit_status": exit_status,
            "observed_work": observed_work,
            "native_manifest_sha256": manifest,
        })
        outcome.validate_admitted_work(reserved_tokens)
    except ValueError:
        return False
    return outcome.native_manifest_sha256 == backend.native_manifest_sha256


def _reconcile_native_reservation_coverage(
    db: sqlite3.Connection, run_id: str, reconciled: set[tuple[int, str, str]],
) -> None:
    """Check for ledger rows outside the scheduler jobs examined for this run."""
    limit = len(reconciled) + 1
    try:
        reservations = db.execute(
            "SELECT id,assignment_id,attempt_id FROM agent_turn_reservations WHERE run_id=? LIMIT ?",
            (run_id, limit),
        ).fetchall()
        # A run that stopped before reserving its first turn may have no native tables.
        has_attempts = db.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='study_token_attempts'"
        ).fetchone() is not None
        has_launches = db.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='study_token_launches'"
        ).fetchone() is not None
        admissions = []
        if has_attempts:
            admissions = db.execute(
                "SELECT turn_reservation_id,assignment_id,attempt_id FROM study_token_attempts "
                "WHERE run_id=? LIMIT ?",
                (run_id, limit),
            ).fetchall()
            if not has_launches:
                raise ValueError("held-out native reservation coverage mismatch")
            launches = db.execute(
                "SELECT turn_reservation_id FROM study_token_launches WHERE run_id=? LIMIT ?",
                (run_id, limit),
            ).fetchall()
        elif has_launches:
            raise ValueError("held-out native reservation coverage mismatch")
        else:
            launches = []
    except sqlite3.OperationalError:
        raise ValueError("held-out native reservation coverage mismatch") from None
    if any(len(rows) != len(reconciled) or set(rows) != reconciled for rows in (reservations, admissions)):
        raise ValueError("held-out native reservation coverage mismatch")
    expected_launches = {reservation_id for reservation_id, _, _ in reconciled}
    actual_launches = {row[0] for row in launches}
    if len(launches) != len(reconciled) or actual_launches != expected_launches:
        raise ValueError("held-out native reservation coverage mismatch")


def reconcile_arm_dispatch(protocol: Protocol, bindings: Bindings, database: Path) -> None:
    """Require each real-model run to carry its bound treatment into host jobs."""
    if protocol.measurement != "real_model":
        return
    expected_digest = digest(protocol)
    backend = protocol.llama_backend
    native_admission = backend is not None and backend.native_manifest_sha256 is not None
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.execute("BEGIN")
        for assignment in bindings.runs:
            recorded = binding(database, assignment.run_id)
            if recorded is None:
                raise ValueError("held-out arm binding mismatch")
            prompt_text = recorded.get("prompt_text")
            if not isinstance(prompt_text, str) or hashlib.sha256(prompt_text.encode()).hexdigest() != (
                    protocol.arm_config[assignment.arm].prompt_sha256):
                raise ValueError("held-out prompt binding mismatch")
            expected_binding = {
                "protocol_sha256": expected_digest, "task_id": assignment.task_id,
                "repetition": assignment.repetition, "arm": assignment.arm,
                "arm_config": protocol.arm_config[assignment.arm].model_dump(mode="json"),
                "model_pin": protocol.model_pin, "runtime_pin": protocol.runtime_pin,
                "budget": protocol.budgets[assignment.arm].model_dump(mode="json"),
            }
            admission_fields = {
                "study_id": protocol.study_id, "measurement": protocol.measurement,
                "memory_card_digests": protocol.memory_card_digests,
            }
            # V1 bindings issued before admission stored none of these fields.
            if native_admission or admission_fields.keys() & recorded.keys():
                expected_binding.update(admission_fields)
            if backend is not None:
                expected_binding["llama_backend"] = backend.model_dump(mode="json", exclude_none=True)
            if {key: value for key, value in recorded.items() if key != "prompt_text"} != expected_binding:
                raise ValueError("held-out arm binding mismatch")
            jobs = db.execute("SELECT assignment_id,state FROM agent_jobs WHERE run_id=?",
                              (assignment.run_id,)).fetchall()
            if not jobs:
                raise ValueError("held-out dispatch evidence missing")
            native_reservations: set[tuple[int, str, str]] = set()
            for assignment_id, state in jobs:
                rows = db.execute("SELECT attempt_id,detail FROM agent_job_log WHERE assignment_id=? "
                                  "AND event='heldout_arm_applied'", (assignment_id,)).fetchall()
                if not rows:
                    raise ValueError("held-out dispatch evidence missing")
                reservations = db.execute(
                    "SELECT rowid,attempt_id,run_id FROM agent_turn_reservations WHERE assignment_id=?",
                    (assignment_id,),
                ).fetchall()
                events = db.execute(
                    "SELECT attempt_id,event,detail FROM agent_job_log WHERE assignment_id=? "
                    "AND event IN ('heldout_prompt_applied','codex_turn','model_turn_abandoned')",
                    (assignment_id,),
                ).fetchall()
                by_id: dict[int, list[tuple[str, str, dict[str, Any]]]] = {}
                for attempt, event, detail in events:
                    try:
                        parsed = json.loads(detail)
                    except (TypeError, json.JSONDecodeError):
                        raise ValueError("held-out prompt dispatch mismatch") from None
                    identity = parsed.get("reservation_id") if isinstance(parsed, dict) else None
                    if type(identity) is not int:
                        raise ValueError("held-out prompt dispatch mismatch")
                    by_id.setdefault(identity, []).append((attempt, event, parsed))
                if set(by_id) != {identity for identity, _, _ in reservations}:
                    raise ValueError("held-out prompt dispatch mismatch")
                for identity, attempt, reservation_run_id in reservations:
                    if not any(recorded_attempt == attempt for recorded_attempt, _ in rows):
                        raise ValueError("held-out dispatch treatment mismatch")
                    matched = by_id[identity]
                    if any(recorded_attempt != attempt for recorded_attempt, _, _ in matched):
                        raise ValueError("held-out prompt dispatch mismatch")
                    kinds = sorted(event for _, event, _ in matched)
                    if kinds == ["model_turn_abandoned"] and not native_admission:
                        continue
                    abandoned_native = kinds == ["heldout_prompt_applied", "model_turn_abandoned"]
                    if not abandoned_native and kinds != ["codex_turn", "heldout_prompt_applied"]:
                        raise ValueError("held-out prompt dispatch mismatch")
                    prompt = next(detail for _, event, detail in matched if event == "heldout_prompt_applied")
                    prompt_sha256 = prompt.get("prompt_sha256")
                    if (prompt.get("prefix_sha256") != protocol.arm_config[assignment.arm].prompt_sha256
                            or not isinstance(prompt_sha256, str)
                            or not re.fullmatch(r"[0-9a-f]{64}", prompt_sha256)
                            or prompt.get("model") != protocol.model_pin
                            or prompt.get("runtime") != protocol.runtime_pin):
                        raise ValueError("held-out prompt dispatch mismatch")
                    if native_admission:
                        if reservation_run_id != assignment.run_id or not _native_dispatch_matches(
                            db, protocol, assignment, protocol_sha256=expected_digest, assignment_id=assignment_id,
                            attempt_id=attempt, reservation_id=identity, prompt_sha256=prompt_sha256,
                            abandoned=abandoned_native,
                        ):
                            raise ValueError("held-out prompt dispatch mismatch")
                        native_reservations.add((identity, assignment_id, attempt))
                expected_cards = len(protocol.memory_card_digests) if protocol.arm_config[assignment.arm].memory_enabled else 0
                for _, detail in rows:
                    applied = json.loads(detail)
                    if applied != {"protocol_sha256": expected_digest, "arm": assignment.arm,
                                   "memory_cards": expected_cards, "model": protocol.model_pin,
                                   "runtime": protocol.runtime_pin}:
                        raise ValueError("held-out dispatch treatment mismatch")
            if native_admission:
                _reconcile_native_reservation_coverage(db, assignment.run_id, native_reservations)


def _finalize(protocol: Protocol, bindings: Bindings, database: Path, *, expected_sha256: str,
              verified_control_attestation: object | None = None,
              control_manifest_sha256: str | None = None,
              control_signature_sha256: str | None = None,
              reviewer_key_sha256: str | None = None) -> dict[str, Any]:
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
    reconcile_arm_dispatch(protocol, bindings, database)
    data = protocol.model_dump()
    data.pop("arm_config")
    data.pop("memory_card_digests")
    data.pop("llama_backend")
    data.pop("control_reviewer_key_sha256")
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
    authenticated_controls = verified_control_attestation is not None
    analysis = (_analyze_with_verified_controls(study) if authenticated_controls else analyze(study))
    return {"protocol_sha256": actual,
            "control_attestation_status": "verified" if authenticated_controls else "absent",
            "control_attestation_sha256": control_manifest_sha256,
            "control_signature_sha256": control_signature_sha256,
            "trusted_reviewer_key_sha256": reviewer_key_sha256,
            "study": study.model_dump(mode="json"),
            "analysis": analysis,
            "ledger_reconciliation": reconcile_evidence(study, database)}


def finalize(protocol: Protocol, bindings: Bindings, database: Path,
             *, expected_sha256: str) -> dict[str, Any]:
    """Export exploratory results; task-control claims remain acceptance-ineligible."""
    return _finalize(protocol, bindings, database, expected_sha256=expected_sha256,
                     verified_control_attestation=None)


def finalize_acceptance(
    protocol: Protocol,
    bindings: Bindings,
    database: Path,
    *,
    expected_sha256: str,
    control_manifest: bytes,
    control_signature: bytes,
    trusted_reviewer_key: Ed25519PublicKey,
) -> dict[str, Any]:
    """Finalize acceptance analysis only with the reviewer key pinned in the protocol."""
    if protocol.control_reviewer_key_sha256 is None:
        raise ValueError("protocol does not pin an independent control reviewer key")
    raw_key = trusted_reviewer_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_digest = hashlib.sha256(raw_key).hexdigest()
    if not hmac.compare_digest(key_digest, protocol.control_reviewer_key_sha256):
        raise ValueError("trusted reviewer key does not match preregistered protocol pin")
    from metis.evaluation.heldout_control_attestation import verify

    attestation = verify(protocol, control_manifest, control_signature,
                         trusted_reviewer_key=trusted_reviewer_key)
    return _finalize(
        protocol, bindings, database, expected_sha256=expected_sha256,
        verified_control_attestation=attestation,
        control_manifest_sha256=hashlib.sha256(control_manifest).hexdigest(),
        control_signature_sha256=hashlib.sha256(control_signature).hexdigest(),
        reviewer_key_sha256=key_digest,
    )


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
    bind_command = commands.add_parser("bind")
    bind_command.add_argument("protocol", type=Path)
    bind_command.add_argument("--database", type=Path, required=True)
    bind_command.add_argument("--expected-sha256", required=True)
    bind_command.add_argument("--run-id", required=True)
    bind_command.add_argument("--task-id", required=True)
    bind_command.add_argument("--repetition", type=int, required=True)
    bind_command.add_argument("--arm", required=True)
    bind_command.add_argument("--prompt-file", type=Path)
    finish = commands.add_parser("finalize")
    finish.add_argument("protocol", type=Path)
    finish.add_argument("bindings", type=Path)
    finish.add_argument("--database", type=Path, required=True)
    finish.add_argument("--expected-sha256", required=True)
    accept = commands.add_parser("finalize-acceptance")
    accept.add_argument("protocol", type=Path)
    accept.add_argument("bindings", type=Path)
    accept.add_argument("--database", type=Path, required=True)
    accept.add_argument("--expected-sha256", required=True)
    accept.add_argument("--control-manifest", type=Path, required=True)
    accept.add_argument("--control-signature", type=Path, required=True)
    accept.add_argument("--trusted-reviewer-key", type=Path, required=True)
    args = parser.parse_args()
    try:
        protocol = Protocol.model_validate_json(_read(args.protocol, MAX_PROTOCOL_BYTES))
        output: dict[str, Any]
        if args.command == "prepare":
            output = {"protocol_sha256": digest(protocol), "schedule": schedule(protocol)}
        elif args.command == "bind":
            prompt_text = (_read(args.prompt_file, 4_000).decode("utf-8")
                           if args.prompt_file is not None else None)
            bind_run(protocol, args.database, args.run_id, task_id=args.task_id,
                     repetition=args.repetition, arm=args.arm,
                     expected_sha256=args.expected_sha256, prompt_text=prompt_text)
            output = {"run_id": args.run_id, "bound": True}
        elif args.command == "finalize":
            bindings = Bindings.model_validate_json(_read(args.bindings, MAX_BINDINGS_BYTES))
            output = finalize(protocol, bindings, args.database,
                              expected_sha256=args.expected_sha256)
        else:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            from metis.evaluation.heldout_control_attestation import MAX_ATTESTATION_BYTES

            bindings = Bindings.model_validate_json(_read(args.bindings, MAX_BINDINGS_BYTES))
            output = finalize_acceptance(
                protocol, bindings, args.database, expected_sha256=args.expected_sha256,
                control_manifest=_read(args.control_manifest, MAX_ATTESTATION_BYTES),
                control_signature=_read(args.control_signature, 64),
                trusted_reviewer_key=Ed25519PublicKey.from_public_bytes(
                    _read(args.trusted_reviewer_key, 32),
                ),
            )
    except (OSError, ValueError, TypeError, sqlite3.Error):
        print("held-out protocol rejected", file=sys.stderr)
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
