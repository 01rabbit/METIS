"""Offline verification and one-shot review of signed Issue #6 calibration grants.

The deployment supplies a trusted Ed25519 operator public key and a private
canonical ledger. An external operator signs grants. This module neither issues
grants nor exposes an execution capability.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import stat
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Annotated, Literal, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .issue6_build_preflight import NATIVE_SHA256, VERSION
from .issue6_pilot_admission import (
    CASE_COUNT,
    COHORT_SECONDS,
    MAX_CALLS,
    PHASE_SECONDS,
    Digest,
    FrozenCase,
)

_DOMAIN = b"METIS Issue #6 live build-triage calibration grant v1\x00"
_DB = "issue6-live-reviews.sqlite"
GrantId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
UnixSeconds = Annotated[int, Field(gt=0, le=2**53 - 1)]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")


class LiveCalibrationPlan(_Record):
    """Expected context supplied by the offline reviewer independently of the grant."""

    source_sha256: Digest
    protocol_sha256: Digest
    native_sha256: Digest
    runtime_version: Literal["0.169.0"]
    model: Literal["gpt-6.1-sol"]
    effort: Literal["low"]
    account_binding: Digest
    workspace_binding: Digest
    phase_schema_sha256: tuple[Digest, Digest]
    cases: Annotated[tuple[FrozenCase, ...], Field(min_length=CASE_COUNT, max_length=CASE_COUNT)]

    @field_validator("native_sha256")
    @classmethod
    def pinned_native(cls, value: str) -> str:
        if value != NATIVE_SHA256:
            raise ValueError("live calibration requires the pinned native Codex hash")
        return value

    @model_validator(mode="after")
    def fixed_distinct_study(self) -> Self:
        if self.runtime_version != VERSION:
            raise ValueError("live calibration version must match the offline native pin")
        if len({case.case_id for case in self.cases}) != CASE_COUNT:
            raise ValueError("case IDs must be distinct")
        if len({case.artifact_hmac for case in self.cases}) != CASE_COUNT:
            raise ValueError("artifact commitments must be distinct")
        return self


class LiveCalibrationGrant(_Record):
    grant_id: GrantId
    mode: Literal["live_calibration"]
    ledger_binding: Digest
    plan: LiveCalibrationPlan
    issued_at: UnixSeconds
    expires_at: UnixSeconds

    @model_validator(mode="after")
    def expiry_follows_issuance(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("grant expiry must follow issuance")
        return self

    def signing_bytes(self) -> bytes:
        """Canonical domain-separated payload for external operator signing."""
        document = {
            "grant": self.model_dump(mode="json"),
            "limits": {
                "cases": CASE_COUNT,
                "max_calls": MAX_CALLS,
                "phase_seconds": PHASE_SECONDS,
                "cohort_seconds": COHORT_SECONDS,
            },
        }
        return _DOMAIN + json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


class LiveGrantReview:
    """Consume one signed grant for offline review, without producing a launch token."""

    def __init__(self, operator_state: Path, *, trusted_operator_key: Ed25519PublicKey,
                 clock: Callable[[], float] = time.time):
        directory = operator_state.resolve(strict=True)
        info = directory.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("live approval requires a private operator-owned state directory")
        self._database = directory / _DB
        self._operator = trusted_operator_key
        self._clock = clock
        self.ledger_binding = hashlib.sha256(os.fsencode(self._database)).hexdigest()

    def _open(self) -> sqlite3.Connection:
        path = self._database
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            raise ValueError("live approval ledger must be a private operator-owned regular file")
        return sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, isolation_level=None)

    def consume_for_review(self, grant: LiveCalibrationGrant, signature: bytes,
                           expected: LiveCalibrationPlan) -> None:
        """Record a single offline use after authenticating the exact calibration plan."""
        grant = LiveCalibrationGrant.model_validate(grant)
        expected = LiveCalibrationPlan.model_validate(expected)
        if grant.ledger_binding != self.ledger_binding or grant.plan != expected:
            raise ValueError("live grant does not match the trusted ledger or calibration plan")
        payload = grant.signing_bytes()
        try:
            self._operator.verify(signature, payload)
        except InvalidSignature:
            raise ValueError("invalid live grant operator signature") from None

        with closing(self._open()) as db:
            db.execute("BEGIN IMMEDIATE")
            path = next(path for _, name, path in db.execute("PRAGMA database_list") if name == "main")
            if Path(path) != self._database:
                raise ValueError("opened live ledger does not match grant binding")
            now = self._clock()
            if not math.isfinite(now) or not grant.issued_at <= now < grant.expires_at:
                raise ValueError("live grant is expired, not yet valid, or clock unavailable")
            db.execute("""CREATE TABLE IF NOT EXISTS offline_live_grant_reviews (
                grant_id TEXT PRIMARY KEY, grant_sha256 TEXT NOT NULL, reviewed_at REAL NOT NULL
            )""")
            written = db.execute(
                "INSERT INTO offline_live_grant_reviews VALUES (?, ?, ?) ON CONFLICT(grant_id) DO NOTHING",
                (grant.grant_id, hashlib.sha256(payload).hexdigest(), now),
            )
            if written.rowcount != 1:
                raise ValueError("live grant has already been consumed for offline review")
            db.execute("COMMIT")
