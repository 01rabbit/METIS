"""Persistent token allowances for a trusted study controller.

The native runtime must independently enforce each allowance before doing any
model work. Admission alone does not make a runner hard-cap capable.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:@+-]{0,127}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Tokens = Annotated[int, Field(ge=1, le=10_000_000)]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")


class StudyTokenPin(_Record):
    study_id: Identifier
    protocol_sha256: Digest
    runtime_sha256: Digest
    model_sha256: Digest
    token_limit: Tokens


class SlotTokenPin(_Record):
    run_id: Identifier
    task_id: Identifier
    repetition: Annotated[int, Field(ge=0, lt=20)]
    arm: Identifier
    token_limit: Tokens


class TokenAttempt(_Record):
    assignment_id: Identifier
    attempt_id: Identifier
    turn_reservation_id: Annotated[int, Field(ge=1, le=2**63 - 1)]
    prompt_sha256: Digest
    tokens: Tokens


class TokenAdmissionReceipt(_Record):
    study: StudyTokenPin
    slot: SlotTokenPin
    attempt: TokenAttempt


_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS study_token_pins (
        study_id TEXT PRIMARY KEY, protocol_sha256 TEXT NOT NULL UNIQUE,
        runtime_sha256 TEXT NOT NULL, model_sha256 TEXT NOT NULL, token_limit INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS study_token_slots (
        run_id TEXT PRIMARY KEY, study_id TEXT NOT NULL, task_id TEXT NOT NULL,
        repetition INTEGER NOT NULL, arm TEXT NOT NULL, token_limit INTEGER NOT NULL,
        UNIQUE (study_id, task_id, repetition, arm),
        UNIQUE (study_id, run_id),
        FOREIGN KEY (study_id) REFERENCES study_token_pins(study_id)
    )""",
    """CREATE TABLE IF NOT EXISTS study_token_attempts (
        study_id TEXT NOT NULL, run_id TEXT NOT NULL, turn_reservation_id INTEGER NOT NULL,
        assignment_id TEXT NOT NULL, attempt_id TEXT NOT NULL, prompt_sha256 TEXT NOT NULL,
        tokens INTEGER NOT NULL CHECK (tokens > 0),
        PRIMARY KEY (run_id, turn_reservation_id),
        FOREIGN KEY (study_id, run_id) REFERENCES study_token_slots(study_id, run_id)
    )""",
    """CREATE INDEX IF NOT EXISTS study_token_attempts_by_study ON study_token_attempts(study_id)""",
)


class StudyTokenAdmission:
    """Atomically charge both ceilings from append-only receipts.

    The controller supplies pins from its committed protocol and bound run.
    A successful receipt is single-use. A timeout, error or retry never refunds
    its charge. All workers must use the same trusted SQLite database.
    """

    def __init__(self, database: Path):
        self.database = database.resolve()

    def reserve(
        self, study: StudyTokenPin, slot: SlotTokenPin, attempt: TokenAttempt,
    ) -> TokenAdmissionReceipt:
        receipt = TokenAdmissionReceipt(study=study, slot=slot, attempt=attempt)
        study, slot, attempt = receipt.study, receipt.slot, receipt.attempt
        if slot.token_limit > study.token_limit:
            raise ValueError("slot token ceiling exceeds study ceiling")
        study_pin = (study.protocol_sha256, study.runtime_sha256,
                     study.model_sha256, study.token_limit)
        slot_pin = (study.study_id, slot.task_id, slot.repetition, slot.arm, slot.token_limit)
        with closing(sqlite3.connect(self.database, timeout=5)) as db, db:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("BEGIN IMMEDIATE")
            for statement in _SCHEMA:
                db.execute(statement)

            db.execute("INSERT OR IGNORE INTO study_token_pins VALUES (?, ?, ?, ?, ?)",
                       (study.study_id, *study_pin))
            recorded_study = db.execute(
                "SELECT protocol_sha256, runtime_sha256, model_sha256, token_limit "
                "FROM study_token_pins WHERE study_id = ?", (study.study_id,),
            ).fetchone()
            if recorded_study != study_pin:
                raise ValueError("study token pin mismatch")

            db.execute("INSERT OR IGNORE INTO study_token_slots VALUES (?, ?, ?, ?, ?, ?)",
                       (slot.run_id, *slot_pin))
            recorded_slot = db.execute(
                "SELECT study_id, task_id, repetition, arm, token_limit FROM study_token_slots "
                "WHERE run_id = ?", (slot.run_id,),
            ).fetchone()
            if recorded_slot != slot_pin:
                raise ValueError("run or study slot token pin mismatch")

            if db.execute(
                "SELECT 1 FROM study_token_attempts WHERE run_id = ? AND turn_reservation_id = ?",
                (slot.run_id, attempt.turn_reservation_id),
            ).fetchone():
                raise ValueError("model turn already has a token receipt")

            (study_used,) = db.execute(
                "SELECT COALESCE(SUM(tokens), 0) FROM study_token_attempts WHERE study_id = ?",
                (study.study_id,),
            ).fetchone()
            (run_used,) = db.execute(
                "SELECT COALESCE(SUM(tokens), 0) FROM study_token_attempts WHERE run_id = ?",
                (slot.run_id,),
            ).fetchone()
            if study_used + attempt.tokens > study.token_limit:
                raise ValueError("study token budget exhausted")
            if run_used + attempt.tokens > slot.token_limit:
                raise ValueError("run token budget exhausted")

            db.execute(
                "INSERT INTO study_token_attempts (study_id, run_id, turn_reservation_id, "
                "assignment_id, attempt_id, prompt_sha256, tokens) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (study.study_id, slot.run_id, attempt.turn_reservation_id, attempt.assignment_id,
                 attempt.attempt_id, attempt.prompt_sha256, attempt.tokens),
            )
        return receipt
