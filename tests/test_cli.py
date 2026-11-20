import io
import json
import subprocess
import sys
from pathlib import Path

from metis.core import ctf_workflow
from metis.core.codex_session import CodexSession
from metis.core.contracts import RunStatus
from metis.core.ctf_web import WebWorkflow
from metis.core.ctf_workflow import WorkflowCapabilityApprovals

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


def test_operator_wires_preview_only_credential_retention_callback(tmp_path, monkeypatch, capsys):
    from metis.cli import main

    database = tmp_path / "state.sqlite"
    WebWorkflow(database)
    captured = {}

    class Server:
        server_port = 45678

        def serve_forever(self, *, poll_interval):
            assert poll_interval == 0.2
            raise KeyboardInterrupt

        def server_close(self):
            pass

    def fake_create_server(path, **kwargs):
        captured["database"] = path
        captured.update(kwargs)
        return Server()

    monkeypatch.setattr("metis.cli.create_server", fake_create_server)
    monkeypatch.setenv("METIS_OPERATOR_TOKEN", "operator-secret-token-with-32-characters")
    monkeypatch.setattr(sys, "argv", ["metis", "operator", "--database", str(database)])
    assert main() == 0
    assert captured["database"] == database
    assert callable(captured["credential_retention_preview"])
    result = captured["credential_retention_preview"](30)
    assert result["applied"] is False and result["older_than_days"] == 30
    assert "METIS operator view: http://127.0.0.1:45678/" in capsys.readouterr().out


def test_audit_is_read_only_and_omits_free_form_event_details(tmp_path):
    database = tmp_path / "runs.sqlite"
    prepared = json.loads(cli("prepare", FIXTURE, "--database", database).stdout)
    from metis.core.contracts import RunEvent, RunStatus
    from metis.core.store import RunStore
    RunStore(database).append(RunEvent(run_id=prepared["run_id"], sequence=2,
                                       status=RunStatus.CLASSIFIED,
                                       detail={"private": "never-print-this"}))
    before = database.read_bytes()
    result = cli("audit", prepared["run_id"], "--database", database)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "classified"
    assert summary["event_count"] == 3
    assert summary["first_sequence"] == 0 and summary["last_sequence"] == 2
    assert summary["status_counts"]["new"] == 1
    assert summary["status_counts"]["validated"] == 1
    assert summary["status_counts"]["classified"] == 1
    assert summary["chain_valid"] is True
    assert "never-print-this" not in result.stdout
    assert database.read_bytes() == before
    repeated = cli("audit", prepared["run_id"], "--database", database)
    assert repeated.returncode == 0, repeated.stderr
    assert repeated.stdout == result.stdout


def test_audit_fails_closed_on_corrupt_chain_and_missing_database(tmp_path):
    missing = tmp_path / "missing.sqlite"
    assert cli("audit", "absent", "--database", missing).returncode == 2
    assert not missing.exists()

    database = tmp_path / "runs.sqlite"
    prepared = json.loads(cli("prepare", FIXTURE, "--database", database).stdout)
    import sqlite3
    with sqlite3.connect(database) as db:
        db.execute("DROP TRIGGER deny_update")
        db.execute("UPDATE events SET payload=? WHERE run_id=? AND sequence=0",
                   ('{"status":"corrupt"}', prepared["run_id"]))
    before = database.read_bytes()
    result = cli("audit", prepared["run_id"], "--database", database)
    assert result.returncode == 2
    assert "unavailable or corrupt" in result.stderr
    assert "Traceback" not in result.stderr
    assert database.read_bytes() == before


def test_cli_purge_derived_defaults_to_preview_and_apply_is_explicit(tmp_path):
    database = tmp_path / "runs.sqlite"
    source = tmp_path / "source.txt"
    source.write_text("fixture")
    session = CodexSession(database)
    run_id = session.intake(title="retention", description="local fixture", paths=[source])["run_id"]
    derived = session.store_artifact(run_id, b"generated")
    session._emit(run_id, RunStatus.CANCELLED)
    root = session.artifact_root(run_id)
    assert root is not None
    derived_file = root / derived

    preview = cli("codex", "--database", database, "purge-derived", run_id)
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)["applied"] is False
    assert derived_file.exists()

    applied = cli("codex", "--database", database, "purge-derived", run_id, "--apply")
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["applied"] is True
    assert not derived_file.exists()


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


def test_workflow_capability_requires_exact_operator_confirmation(tmp_path, monkeypatch, capsys):
    database = tmp_path / "runs.sqlite"
    fixture = tmp_path / "source.txt"
    fixture.write_text("local fixture")
    run_id = CodexSession(database).intake(title="Local workflow review", description="Fixture only",
                                          paths=[fixture], categories=["misc"])["run_id"]
    approvals = WorkflowCapabilityApprovals(database)
    monkeypatch.setattr(sys, "argv", ["metis", "workflow", "--database", str(database),
                                      "approve", run_id, "rot13_decode"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")
    from metis.cli import main
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("unconfirmed capability approval unexpectedly succeeded")
    assert "rot13_decode" not in approvals.approved_tools(run_id)
    monkeypatch.setattr("builtins.input", lambda _prompt: (_ for _ in ()).throw(EOFError()))
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("EOF during capability review unexpectedly succeeded")
    assert "rot13_decode" not in approvals.approved_tools(run_id)

    v1 = ctf_workflow.capability_review_details("rot13_decode")
    old_confirmation = (f"APPROVE rot13_decode v{v1['descriptor']['version']} "
                        f"sha256:{v1['capability_sha256']} {run_id}")
    original_descriptor = ctf_workflow._capability_descriptor
    monkeypatch.setattr(ctf_workflow, "_capability_descriptor",
                        lambda tool: {**original_descriptor(tool), "version": 2})
    monkeypatch.setattr("builtins.input", lambda _prompt: old_confirmation)
    try:
        main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("confirmation for an old descriptor unexpectedly approved a new version")
    assert "rot13_decode" not in approvals.approved_tools(run_id)
    preview = capsys.readouterr().out
    v2 = ctf_workflow.capability_review_details("rot13_decode")
    assert '"version": 2' in preview
    assert v2["capability_sha256"] in preview
    new_confirmation = (f"APPROVE rot13_decode v{v2['descriptor']['version']} "
                        f"sha256:{v2['capability_sha256']} {run_id}")
    monkeypatch.setattr("builtins.input", lambda _prompt: new_confirmation)
    monkeypatch.setattr("getpass.getuser", lambda: "test-operator")
    assert main() == 0
    assert "rot13_decode" in approvals.approved_tools(run_id)
    approval_output = capsys.readouterr().out
    assert v2["capability_sha256"] in approval_output
    assert json.loads(approval_output.splitlines()[-1])["reviewer"] == "test-operator"
    monkeypatch.setattr(sys, "argv", ["metis", "workflow", "--database", str(database),
                                      "status", run_id])
    assert main() == 0
    status = json.loads(capsys.readouterr().out)
    assert "rot13_decode" in status["approved_tools"]
    assert status["reviews"][0]["capability_sha256"]
