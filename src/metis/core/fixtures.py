"""Generate synthetic development puzzles and a separate private answer store."""
from __future__ import annotations

import base64
import json
import os
import secrets
from pathlib import Path

from metis.core.contracts import ChallengeManifest


def generate_fixtures(challenge_dir: Path, oracle_path: Path) -> list[Path]:
    if oracle_path.resolve().is_relative_to(challenge_dir.resolve()):
        raise ValueError("oracle must be outside the challenge directory")
    challenge_dir.mkdir(parents=True, exist_ok=True)
    oracle_path.parent.mkdir(parents=True, exist_ok=True)
    answers: dict[str, str] = {}
    paths = []
    manifests = []
    for category, transform in [("crypto", "base64_decode"), ("misc", "hex_decode")]:
        challenge_id = f"generated-{category}-{secrets.token_hex(4)}"
        answer = "METIS{" + secrets.token_hex(16) + "}"
        encoded = (base64.b64encode(answer.encode()).decode() if category == "crypto"
                   else answer.encode().hex())
        attempts = [{"tool": transform, "data": encoded}]
        if category == "crypto":
            attempts.insert(0, {"tool": "hex_decode", "data": "invalid-hex"})
        manifest = ChallengeManifest.model_validate({
            "challenge_id": challenge_id, "title": "Generated local decoder fixture",
            "description": json.dumps({"attempts": attempts}), "categories": [category],
            "scope": {"authorized": True, "granted_by": "local-fixture-generator",
                      "challenge_id": challenge_id},
        })
        manifests.append(manifest)
        answers[challenge_id] = answer
    # Never overwrite an existing oracle. Keep answer bytes private from creation.
    descriptor = os.open(oracle_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(answers, stream)
    for manifest in manifests:
        path = challenge_dir / f"{manifest.challenge_id}.json"
        with path.open("x") as stream:
            stream.write(manifest.model_dump_json(indent=2))
        paths.append(path)
    return paths
