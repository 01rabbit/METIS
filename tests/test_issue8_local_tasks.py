from __future__ import annotations

import base64
import json
import os
import stat

import pytest

from metis.core.verification import FixtureOracle
from scripts.generate_issue8_local_tasks import generate


def test_generated_tasks_are_reproducible_and_oracle_separate(tmp_path):
    seed = tmp_path / "seed"
    seed.write_bytes(b"x" * 32)
    seed.chmod(0o600)
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest = generate(seed, first)
    assert manifest == generate(seed, second)
    assert len(manifest["tasks"]) == 4
    oracle = FixtureOracle(first / "private" / "answers.json",
                           solver_roots=(first / "public",))
    assert stat.S_IMODE((first / "private" / "answers.json").stat().st_mode) == 0o600
    assert not (first / "public" / "answers.json").exists()
    for task in manifest["tasks"]:
        artifact = first / "public" / task["artifact"]
        assert artifact.read_bytes() == (second / "public" / task["artifact"]).read_bytes()
        data = json.loads(artifact.read_text())
        encoded = data["description"].split(": ", 1)[1]
        answer = (base64.b64decode(encoded).decode() if task["category"] == "crypto"
                  else bytes.fromhex(encoded).decode())
        assert oracle.verify(task["task_id"], answer)
        assert not oracle.verify(task["task_id"], answer + "x")


def test_refuses_public_seed_and_existing_output(tmp_path):
    seed = tmp_path / "seed"
    seed.write_bytes(os.urandom(32))
    seed.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        generate(seed, tmp_path / "output")
    seed.chmod(0o600)
    output = tmp_path / "output"
    generate(seed, output)
    with pytest.raises(FileExistsError):
        generate(seed, output)


def test_refuses_hardlinked_seed_and_symlinked_output(tmp_path):
    seed = tmp_path / "seed"
    seed.write_bytes(os.urandom(32))
    seed.chmod(0o600)
    alias = tmp_path / "alias"
    os.link(seed, alias)
    with pytest.raises(ValueError, match="private"):
        generate(alias, tmp_path / "output")
    alias.unlink()
    target = tmp_path / "target"
    target.mkdir()
    output = tmp_path / "output"
    output.symlink_to(target)
    with pytest.raises(FileExistsError):
        generate(seed, output)
