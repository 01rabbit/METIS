"""Create reproducible synthetic held-out tasks with a separate private oracle.

These local controls test the evaluation plumbing; they are not official CTF solves.
Mount only the public subdirectory for solvers. Keep the private subdirectory and
seed outside the repository and every solver-visible root.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from metis.core.contracts import ChallengeManifest


def _inside_repo(path: Path) -> bool:
    """Compare directory identity, including on case-insensitive filesystems."""
    for ancestor in (path, *path.parents):
        if ancestor.exists() and os.path.samefile(ancestor, ROOT):
            return True
    return False


def _private_seed(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                or info.st_size > 4096 or info.st_nlink != 1):
            raise ValueError("seed must be a private bounded regular file")
        seed = stream.read(4097)
    if len(seed) < 32 or len(seed) > 4096:
        raise ValueError("seed length must be between 32 and 4096 bytes")
    return seed


def generate(seed_path: Path, output: Path) -> dict[str, object]:
    if _inside_repo(seed_path.resolve(strict=True)):
        raise ValueError("seed must be outside the repository")
    seed = _private_seed(seed_path)
    destination = output.resolve(strict=False)
    if _inside_repo(destination.parent):
        raise ValueError("output must be outside the repository")
    if output.is_symlink() or output.exists():
        raise FileExistsError("output already exists")
    if output.parent.resolve(strict=True) != output.parent:
        raise ValueError("output parent must not contain symlinks")

    output.mkdir(mode=0o700)
    public = output / "public"
    private = output / "private"
    public.mkdir(mode=0o700)
    private.mkdir(mode=0o700)
    answers: dict[str, str] = {}
    tasks: list[dict[str, str]] = []
    for category in ("crypto", "misc"):
        for index in range(2):
            label = f"issue8-local-v1:{category}:{index}"
            material = hmac.new(seed, label.encode(), hashlib.sha256).digest()
            challenge_id = f"local-{category}-{index}-{material[:4].hex()}"
            answer = f"METIS{{{material[4:20].hex()}}}"
            if category == "crypto":
                encoded = base64.b64encode(answer.encode()).decode()
                description = f"Decode the Base64 text and report the exact result: {encoded}"
            else:
                encoded = answer.encode().hex()
                description = f"Decode the hexadecimal text and report the exact result: {encoded}"
            manifest = ChallengeManifest.model_validate({
                "challenge_id": challenge_id,
                "title": "Synthetic local decoder control",
                "description": description,
                "categories": [category],
                "scope": {"authorized": True, "granted_by": "local-fixture-generator",
                          "challenge_id": challenge_id},
            })
            payload = manifest.model_dump_json(indent=2).encode()
            artifact = public / f"{challenge_id}.json"
            descriptor = os.open(artifact, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
            answers[challenge_id] = answer
            tasks.append({"task_id": challenge_id, "category": category,
                          "artifact": artifact.name,
                          "distribution_sha256": hashlib.sha256(payload).hexdigest()})

    oracle = private / "answers.json"
    descriptor = os.open(oracle, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(answers, stream, sort_keys=True)
    manifest_data: dict[str, object] = {"schema_version": 1, "kind": "synthetic_local_control",
                                        "tasks": tasks}
    with (public / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest_data, stream, sort_keys=True, indent=2)
    return manifest_data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = generate(args.seed, args.output)
    tasks = result["tasks"]
    assert isinstance(tasks, list)
    print(json.dumps({"status": "created", "kind": result["kind"],
                      "task_count": len(tasks)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
