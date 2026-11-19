"""Persistent token allowances for a trusted study controller.

The native runtime must independently enforce each allowance before doing any
model work. Admission alone does not make a runner hard-cap capable.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class TokenLaunchClaim(_Record):
    receipt: TokenAdmissionReceipt
    nonce: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


class TokenLaunchOutcome(_Record):
    status: Literal[
        "completed", "cap_denied", "unsupported_graph", "server_error",
        "launch_failed", "receipt_invalid", "timeout", "cancelled", "lost",
    ]
    exit_status: Annotated[int, Field(ge=-127, le=255)] | None = None
    observed_work: Annotated[int, Field(ge=0, le=10_000_000)] | None = None

    @model_validator(mode="after")
    def validate_observations(self) -> Self:
        if self.status == "completed":
            valid = self.exit_status == 0 and self.observed_work is not None
        elif self.status in ("cap_denied", "unsupported_graph"):
            valid = self.exit_status == 75 and self.observed_work is not None
        elif self.status == "server_error":
            valid = (self.exit_status is not None and 1 <= self.exit_status <= 255
                     and self.exit_status not in (74, 75) and self.observed_work is not None)
        else:
            valid = self.observed_work is None and (
                self.status not in ("launch_failed", "lost") or self.exit_status is None
            )
        if not valid:
            raise ValueError("terminal observations do not match outcome")
        return self


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
    """CREATE TABLE IF NOT EXISTS study_token_launches (
        run_id TEXT NOT NULL, turn_reservation_id INTEGER NOT NULL, nonce TEXT NOT NULL UNIQUE,
        PRIMARY KEY (run_id, turn_reservation_id),
        FOREIGN KEY (run_id, turn_reservation_id)
            REFERENCES study_token_attempts(run_id, turn_reservation_id)
    )""",
    """CREATE TABLE IF NOT EXISTS study_token_outcomes (
        nonce TEXT PRIMARY KEY NOT NULL,
        status TEXT NOT NULL, exit_status INTEGER, observed_work INTEGER,
        FOREIGN KEY (nonce) REFERENCES study_token_launches(nonce)
    )""",
    """CREATE TABLE IF NOT EXISTS study_token_fixture_claims (
        nonce TEXT PRIMARY KEY NOT NULL,
        FOREIGN KEY (nonce) REFERENCES study_token_launches(nonce)
    )""",
)


_fixture_fd_guard = Lock()
_fixture_lock_fds: set[int] = set()


def _after_fixture_fork() -> None:
    for fd in _fixture_lock_fds:
        os.close(fd)
    _fixture_lock_fds.clear()
    _fixture_fd_guard.release()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_fixture_fd_guard.acquire,
        after_in_parent=_fixture_fd_guard.release,
        after_in_child=_after_fixture_fork,
    )


class FixtureClaimBusy(ValueError):
    """A fixture controller or reconciler still holds the claim lock."""


class StudyTokenAdmission:
    """Atomically charge both ceilings from append-only receipts.

    The trusted caller supplies study and slot pins, which this ledger records
    on the first accepted reservation. It validates the shape of the supplied
    turn reservation ID and rejects a second receipt for the same run and turn.
    This standalone ledger has no integration with the held-out protocol or the
    scheduler's turn reservations. A trusted controller must use a fresh,
    committed claim for each launch. It verifies terminal process evidence
    before recording observations. A timeout, error or retry never refunds
    a charge or makes a claim reusable. All controllers must use the same
    trusted SQLite database.
    """

    def __init__(self, database: Path):
        self.database = database.resolve()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.database, timeout=5)) as db, db:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA synchronous = FULL")
            db.execute("BEGIN IMMEDIATE")
            for statement in _SCHEMA:
                db.execute(statement)
            yield db

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
        with self._transaction() as db:
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


    @staticmethod
    def _require_committed_receipt(db: sqlite3.Connection, receipt: TokenAdmissionReceipt) -> None:
        study, slot, attempt = receipt.study, receipt.slot, receipt.attempt
        stored = db.execute(
            """SELECT p.study_id, p.protocol_sha256, p.runtime_sha256, p.model_sha256, p.token_limit,
                      s.task_id, s.repetition, s.arm, s.token_limit,
                      a.assignment_id, a.attempt_id, a.prompt_sha256, a.tokens
               FROM study_token_attempts AS a
               JOIN study_token_slots AS s ON s.run_id = a.run_id AND s.study_id = a.study_id
               JOIN study_token_pins AS p ON p.study_id = s.study_id
               WHERE a.run_id = ? AND a.turn_reservation_id = ?""",
            (slot.run_id, attempt.turn_reservation_id),
        ).fetchone()
        if stored != (
            study.study_id, study.protocol_sha256, study.runtime_sha256, study.model_sha256, study.token_limit,
            slot.task_id, slot.repetition, slot.arm, slot.token_limit,
            attempt.assignment_id, attempt.attempt_id, attempt.prompt_sha256, attempt.tokens,
        ):
            raise ValueError("token receipt does not match committed reservation")

    def _preflight_fixture_receipt(self, receipt: TokenAdmissionReceipt) -> None:
        with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            self._require_committed_receipt(db, receipt)

    @contextmanager
    def _fixture_lock(self, receipt: TokenAdmissionReceipt) -> Iterator[None]:
        # The generic ledger remains usable on platforms without POSIX flock.
        import fcntl

        directory = self.database.with_name(f".{self.database.name}.fixture-locks")
        directory.mkdir(mode=0o700, exist_ok=True)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            attributes = os.fstat(directory_fd)
            if attributes.st_uid != os.geteuid() or stat.S_IMODE(attributes.st_mode) != 0o700:
                raise ValueError("fixture claims require a private operator-owned lock directory")
            key = f"{receipt.slot.run_id}:{receipt.attempt.turn_reservation_id}".encode("ascii")
            name = hashlib.sha256(key).hexdigest() + ".lock"
            with _fixture_fd_guard:
                fd = os.open(
                    name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                    0o600, dir_fd=directory_fd,
                )
                _fixture_lock_fds.add(fd)
            owner_pid = os.getpid()
            try:
                attributes = os.fstat(fd)
                if (not stat.S_ISREG(attributes.st_mode) or attributes.st_uid != os.geteuid()
                        or stat.S_IMODE(attributes.st_mode) != 0o600 or attributes.st_nlink != 1):
                    raise ValueError("fixture claim lock must be a private operator-owned regular file")
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise FixtureClaimBusy("fixture claim already has an active owner") from None
                yield
            finally:
                # A raw fork child has already closed its inherited copy.
                if os.getpid() == owner_pid:
                    with _fixture_fd_guard:
                        _fixture_lock_fds.remove(fd)
                        # Keep the path so later owners lock the same inode.
                        os.close(fd)
        finally:
            os.close(directory_fd)

    def claim_for_launch(self, receipt: TokenAdmissionReceipt) -> TokenLaunchClaim:
        """Return a one-time launch claim only after its transaction commits."""
        return self._claim_for_launch(receipt, fixture_owned=False)

    @contextmanager
    def claim_fixture_launch(self, receipt: TokenAdmissionReceipt) -> Iterator[TokenLaunchClaim]:
        """Hold exclusive fixture ownership until terminal recording or controller exit."""
        receipt = TokenAdmissionReceipt.model_validate(receipt)
        self._preflight_fixture_receipt(receipt)
        with self._fixture_lock(receipt):
            yield self._claim_for_launch(receipt, fixture_owned=True)

    def _claim_for_launch(self, receipt: TokenAdmissionReceipt, *, fixture_owned: bool) -> TokenLaunchClaim:
        claim = TokenLaunchClaim(receipt=receipt, nonce=secrets.token_hex(16))
        receipt = claim.receipt
        with self._transaction() as db:
            self._require_committed_receipt(db, receipt)
            inserted = db.execute(
                """INSERT INTO study_token_launches (run_id, turn_reservation_id, nonce)
                   VALUES (?, ?, ?) ON CONFLICT DO NOTHING""",
                (receipt.slot.run_id, receipt.attempt.turn_reservation_id, claim.nonce),
            )
            if inserted.rowcount != 1:
                raise ValueError("token launch already claimed or nonce unavailable")
            if fixture_owned:
                db.execute("INSERT INTO study_token_fixture_claims (nonce) VALUES (?)", (claim.nonce,))
        return claim

    def reconcile_lost_fixture_claim(self, receipt: TokenAdmissionReceipt) -> TokenLaunchOutcome:
        """Record a lost controller outcome without implying the worker stopped."""
        receipt = TokenAdmissionReceipt.model_validate(receipt)
        self._preflight_fixture_receipt(receipt)
        with self._fixture_lock(receipt):
            with self._transaction() as db:
                self._require_committed_receipt(db, receipt)
                row = db.execute(
                    """SELECT l.nonce FROM study_token_launches AS l
                       JOIN study_token_fixture_claims AS f ON l.nonce = f.nonce
                       WHERE l.run_id = ? AND l.turn_reservation_id = ?""",
                    (receipt.slot.run_id, receipt.attempt.turn_reservation_id),
                ).fetchone()
                if row is None:
                    raise ValueError("reservation has no recoverable fixture claim")
                claim = TokenLaunchClaim(receipt=receipt, nonce=row[0])
            outcome = TokenLaunchOutcome(status="lost")
            self.record_outcome(claim, outcome)
            return outcome

    def record_outcome(self, claim: TokenLaunchClaim, outcome: TokenLaunchOutcome) -> None:
        """Record one terminal observation without changing the admission charge."""
        claim = TokenLaunchClaim.model_validate(claim)
        outcome = TokenLaunchOutcome.model_validate(outcome)
        receipt = claim.receipt
        if outcome.observed_work is not None and outcome.observed_work > receipt.attempt.tokens:
            raise ValueError("observed work exceeds admitted token allowance")
        with self._transaction() as db:
            self._require_committed_receipt(db, receipt)
            stored = db.execute(
                "SELECT nonce FROM study_token_launches WHERE run_id = ? AND turn_reservation_id = ?",
                (receipt.slot.run_id, receipt.attempt.turn_reservation_id),
            ).fetchone()
            if stored != (claim.nonce,):
                raise ValueError("token launch claim does not match committed nonce")

            inserted = db.execute(
                """INSERT INTO study_token_outcomes (nonce, status, exit_status, observed_work)
                   VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING""",
                (claim.nonce, outcome.status, outcome.exit_status, outcome.observed_work),
            )
            if inserted.rowcount != 1:
                raise ValueError("token launch outcome already recorded")
