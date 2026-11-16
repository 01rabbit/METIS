import io
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


def test_oversized_manifest_is_rejected_before_parsing(tmp_path):
    manifest = tmp_path / "large.json"
    manifest.write_bytes(b"x" * 1_048_577)
    result = cli("validate", manifest)
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_generated_fixture_cli_respects_stop_marker_without_docker(tmp_path):
    oracle = tmp_path / "private/answers.json"
    generated = cli("generate-fixtures", tmp_path / "solver", "--oracle", oracle)
    assert generated.returncode == 0, generated.stderr
    manifest = json.loads(generated.stdout)["manifests"][0]
    marker = tmp_path / "stop"
    marker.touch()
    result = cli("run", manifest, "--database", tmp_path / "runs.sqlite",
                 "--oracle", oracle, "--image", "python@sha256:" + "a" * 64,
                 "--stop-file", marker)
    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)["status"] == "cancelled"


def test_web_submit_removes_one_terminal_line_ending(monkeypatch, tmp_path, capsys):
    captured = []

    class Workflow:
        def __init__(self, database):
            assert database == tmp_path / "runs.sqlite"

        def submit(self, run_id, candidate):
            captured.append((run_id, candidate))
            return {"verified": True}

    monkeypatch.setattr("metis.cli.WebWorkflow", Workflow)
    monkeypatch.setattr(sys, "argv", ["metis", "web", "--database", str(tmp_path / "runs.sqlite"),
                                      "submit", "run-1"])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"FLAG_example\r\n")))
    from metis.cli import main
    assert main() == 0
    assert captured == [("run-1", "FLAG_example")]
    assert json.loads(capsys.readouterr().out)["verified"] is True


def test_agent_slots_can_disable_munin_retrieval(tmp_path):
    result = cli("agent", "--database", tmp_path / "agent.sqlite", "slots", "--no-memory-retrieval")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["memory_retrieval"] is False
