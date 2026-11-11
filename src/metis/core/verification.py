"""Trusted local-fixture oracle. Never pass this component or its store to a solver."""
from __future__ import annotations

import hmac
import json
import os
import stat
from pathlib import Path
from typing import Protocol


class Verifier(Protocol):
    def verify(self, challenge_id: str, candidate: str) -> bool: ...


class FixtureOracle:
    """Read a protected, external fixture answer store; reveal only a verdict.

    The controller owns this component. The model receives no store path or answer
    mapping, and its Docker runtime has no host mounts. A malicious controller
    or database owner is outside this boundary; this is not an official CTF API.
    """

    def __init__(self, path: Path, *, solver_roots: tuple[Path, ...]):
        resolved = path.resolve(strict=True)
        if any(resolved.is_relative_to(root.resolve()) for root in solver_roots):
            raise ValueError("oracle must be outside every solver-visible root")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077
                    or metadata.st_size > 1_048_576):
                raise ValueError("oracle must be a private bounded regular file")
            payload = stream.read(1_048_577)
        values = json.loads(payload)
        if (not isinstance(values, dict) or len(payload) > 1_048_576
                or not all(isinstance(key, str) and isinstance(value, str)
                           for key, value in values.items())):
            raise ValueError("invalid oracle store")
        self.__answers: dict[str, str] = values

    def verify(self, challenge_id: str, candidate: str) -> bool:
        expected = self.__answers.get(challenge_id)
        return expected is not None and hmac.compare_digest(expected.encode(), candidate.encode())
