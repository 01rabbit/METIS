"""Authenticate answer-free held-out control assertions without running a study."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Annotated, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, ValidationError, model_validator

from metis.evaluation.heldout_analysis import Record
from metis.evaluation.heldout_protocol import MAX_PROTOCOL_BYTES, Protocol, digest

_DOMAIN = b"METIS held-out independent control attestation v1\x00"
MAX_ATTESTATION_BYTES = 512_000
_SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ControlRow(Record):
    task_id_sha256: _SHA256
    source_id_sha256: _SHA256
    distribution_sha256: _SHA256
    evidence_sha256: _SHA256
    control: Literal["verified", "unverified"]
    exposure: Literal["unseen", "prior_solved", "prior_answer", "unknown"]


class ControlAttestation(Record):
    schema_version: Annotated[int, Field(ge=1, le=1)]
    role: Literal["independent_control_reviewer"]
    protocol_sha256: _SHA256
    tasks: Annotated[list[ControlRow], Field(min_length=2, max_length=1000)]

    @model_validator(mode="after")
    def unique_tasks(self) -> ControlAttestation:
        if (len({row.task_id_sha256 for row in self.tasks}) != len(self.tasks)
                or len({(row.source_id_sha256, row.distribution_sha256) for row in self.tasks}) != len(self.tasks)):
            raise ValueError("duplicate control task or artifact identity")
        return self


def signing_bytes(attestation: ControlAttestation) -> bytes:
    """Prepare canonical bytes for a separate reviewer-held signer."""
    checked = ControlAttestation.model_validate(attestation.model_dump())
    document = checked.model_dump(mode="json")
    document["tasks"].sort(key=lambda row: row["task_id_sha256"])
    return _DOMAIN + json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _id_digest(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("ascii")).hexdigest()


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("duplicate JSON field")
    return fields


def verify(
    protocol: Protocol,
    manifest: bytes,
    signature: bytes,
    *,
    trusted_reviewer_key: Ed25519PublicKey,
) -> ControlAttestation:
    """Verify the issuer and protocol binding without granting run or scoring authority."""
    if not 0 < len(manifest) <= MAX_ATTESTATION_BYTES or len(signature) != 64:
        raise ValueError("control attestation input outside bounds")
    protocol = Protocol.model_validate(protocol.model_dump())
    try:
        document = json.loads(manifest.decode("ascii"), object_pairs_hook=_unique_keys)
        attestation = ControlAttestation.model_validate(document)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, RecursionError):
        # Parser and schema exceptions can contain caller-controlled material.
        raise ValueError("invalid control attestation document") from None
    if attestation.protocol_sha256 != digest(protocol):
        raise ValueError("control attestation protocol mismatch")
    expected = {
        _id_digest(task.task_id): (
            _id_digest(task.source_id), task.distribution_sha256,
            "verified" if task.solvability_control_verified else "unverified", task.exposure,
        )
        for task in protocol.tasks
    }
    actual = {
        row.task_id_sha256: (row.source_id_sha256, row.distribution_sha256, row.control, row.exposure)
        for row in attestation.tasks
    }
    if actual != expected:
        raise ValueError("control attestation task assertions mismatch")
    try:
        trusted_reviewer_key.verify(signature, signing_bytes(attestation))
    except InvalidSignature:
        raise ValueError("invalid control attestation signature") from None
    return attestation


def _read(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError("control attestation file outside bounds")
        data = stream.read(limit + 1)
    if not 0 < len(data) <= limit:
        raise ValueError("control attestation file outside bounds")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify held-out control assertions offline")
    parser.add_argument("protocol", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("signature", type=Path)
    parser.add_argument("--reviewer-key", type=Path, required=True)
    args = parser.parse_args()
    try:
        protocol = Protocol.model_validate(json.loads(
            _read(args.protocol, MAX_PROTOCOL_BYTES).decode("utf-8"), object_pairs_hook=_unique_keys,
        ))
        attestation = verify(
            protocol, _read(args.manifest, MAX_ATTESTATION_BYTES), _read(args.signature, 64),
            trusted_reviewer_key=Ed25519PublicKey.from_public_bytes(_read(args.reviewer_key, 32)),
        )
    except (OSError, ValueError, RecursionError):
        print("held-out control attestation rejected", file=sys.stderr)
        return 1
    print(json.dumps({"protocol_sha256": attestation.protocol_sha256, "authenticated_task_rows": len(attestation.tasks)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
