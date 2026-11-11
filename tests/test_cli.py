import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "challenges/training/fixture-001.json"


def cli(*args):
    return subprocess.run([sys.executable, "-m", "metis.cli", *map(str, args)],
                          check=False, capture_output=True, text=True)


def test_prepare_and_inspect(tmp_path):
    database = tmp_path / "runs.sqlite"
    result = cli("prepare", FIXTURE, "--database", database)
    assert result.returncode == 0, result.stderr
    prepared = json.loads(result.stdout)
    assert prepared["status"] == "validated"
    before = database.read_bytes()
    result = cli("inspect", prepared["run_id"], "--database", database)
    assert result.returncode == 0, result.stderr
    assert [json.loads(line)["status"] for line in result.stdout.splitlines()] == [
        "new", "validated",
    ]
    assert database.read_bytes() == before
    assert cli("inspect", "absent", "--database", database).returncode == 2


def test_inspect_does_not_create_missing_database(tmp_path):
    database = tmp_path / "missing.sqlite"
    result = cli("inspect", "absent", "--database", database)
    assert result.returncode == 2
    assert not database.exists()


def test_rejected_inputs_are_not_echoed_or_recorded(tmp_path):
    manifest = tmp_path / "invalid.json"
    database = tmp_path / "runs.sqlite"
    manifest.write_text('{"private_answer": "do-not-log-this"}')
    result = cli("prepare", manifest, "--database", database)
    assert result.returncode == 2
    assert "do-not-log-this" not in result.stdout + result.stderr
    assert not database.exists()


def test_invalid_encoding_is_rejected_without_traceback(tmp_path):
    manifest = tmp_path / "invalid.json"
    manifest.write_bytes(b"\xff")
    result = cli("validate", manifest)
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
