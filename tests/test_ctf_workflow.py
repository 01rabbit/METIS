"""Bounded declarative workflows cannot add tools, policy, verifier or code."""
import base64
import hashlib
import json
import os
import secrets
import sqlite3
import sys

import pytest

from metis.core import ctf_workflow
from metis.core.artifacts import read_artifact
from metis.core.codex_session import CodexSession
from metis.core.ctf_artifacts import ARTIFACT_TOOLS
from metis.core.ctf_sandbox import configure
from metis.core.ctf_workflow import (
    BASE_WORKFLOW_TOOLS,
    MAX_WORKFLOW_OUTPUT,
    WorkflowCandidate,
    WorkflowCapabilityApprovals,
    _validate_workflow_output,
    capability_digest,
    generate_seeded_workflow,
    replay_workflow_in_sandbox,
    run_workflow_in_sandbox,
    sandbox_runner_script,
    validate_workflow,
    verify_workflow_digest,
)


def test_seeded_workflow_families_are_reproducible_and_keep_oracle_separate():
    seeds = ((secrets.randbits(31) * 2, ["base32_decode", "base64_decode"]),
             (secrets.randbits(31) * 2 + 1, ["base64_decode", "hex_decode"]))
    for seed, expected_tools in seeds:
        first = generate_seeded_workflow(seed)
        second = generate_seeded_workflow(seed)
        assert first == second
        assert first.challenge_sha256
        assert json.loads(first.workflow_json)["input_artifact"] == "challenge.txt"
        assert [step["tool"] for step in json.loads(first.workflow_json)["steps"]] == expected_tools
        assert first.oracle_sha256 not in first.workflow_json.decode()
        assert first.challenge not in first.workflow_json


def test_workflow_schema_rejects_new_tool_policy_verifier_and_code():
    valid = {"schema_version": 1, "input_artifact": "challenge.txt",
             "steps": [{"tool": "base64_decode"}]}
    assert validate_workflow(json.dumps(valid), input_artifact="challenge.txt")
    for changes in (
        {"steps": [{"tool": "shell"}]},
        {"policy": {"allow_network": True}},
        {"verifier": "always true"},
        {"code": "open('/etc/passwd').read()"},
        {"input_artifact": "../outside"},
    ):
        with pytest.raises(ValueError):
            validate_workflow(json.dumps({**valid, **changes}), input_artifact="challenge.txt")
    proposed = {**valid, "steps": [{"tool": "rot13_decode"}]}
    with pytest.raises(ValueError, match="unregistered tool"):
        validate_workflow(json.dumps(proposed), input_artifact="challenge.txt")


def test_sandbox_runner_is_fixed_allowlisted_and_returns_bounded_output():
    script = sandbox_runner_script()
    assert 'ALLOWED = set(["base32_decode","base64_decode","hex_decode"])' in script
    assert "hashlib.sha256(value).hexdigest()" in script
    assert "output_bytes" in script
    assert "MAX_OUTPUT_BYTES = 16384" in script
    assert "output_b64" in script
    assert "subprocess" not in script
    assert "socket" not in script
    assert {"base32_decode", "base64_decode", "hex_decode"} <= ARTIFACT_TOOLS
    assert "rot13_decode" not in ARTIFACT_TOOLS
    assert 'ALLOWED = set(["base32_decode","base64_decode","hex_decode"])' in script


def test_capability_approval_is_explicit_per_run_digest_bound_and_revocable(tmp_path, monkeypatch):
    database = tmp_path / "state" / "metis.sqlite"
    source = tmp_path / "source.txt"
    source.write_bytes(b"synthetic fixture")
    session = CodexSession(database)
    first = session.intake(title="Workflow approval A", description="Local only",
                           paths=[source], categories=["misc"])
    second = session.intake(title="Workflow approval B", description="Local only",
                            paths=[source], categories=["misc"])
    first_run, second_run = first["run_id"], second["run_id"]
    approvals = WorkflowCapabilityApprovals(database)
    assert approvals.approved_tools(first_run) == BASE_WORKFLOW_TOOLS
    assert approvals.approved_tools(second_run) == BASE_WORKFLOW_TOOLS
    assert len(capability_digest("rot13_decode")) == 64

    approved = approvals.record(first_run, "rot13_decode", decision="approve", reviewer="operator",
                                expected_digest=capability_digest("rot13_decode"))
    assert approved["capability_sha256"] == capability_digest("rot13_decode")
    assert "rot13_decode" in approvals.approved_tools(first_run)
    original_function = ctf_workflow._capability_descriptor
    monkeypatch.setattr(ctf_workflow, "_capability_descriptor",
                        lambda tool: {**original_function(tool), "version": 2})
    assert "rot13_decode" not in approvals.approved_tools(first_run)
    with pytest.raises(ValueError, match="changed after review"):
        approvals.record(first_run, "rot13_decode", decision="approve", reviewer="operator",
                         expected_digest=approved["capability_sha256"])
    monkeypatch.setattr(ctf_workflow, "_capability_descriptor", original_function)
    assert "rot13_decode" not in approvals.approved_tools(second_run)
    workflow = {"schema_version": 1, "input_artifact": "source.txt",
                "steps": [{"tool": "rot13_decode"}]}
    assert validate_workflow(json.dumps(workflow), input_artifact="source.txt",
                             approved_tools=approvals.approved_tools(first_run))
    with pytest.raises(ValueError, match="unregistered tool"):
        validate_workflow(json.dumps(workflow), input_artifact="source.txt",
                          approved_tools=approvals.approved_tools(second_run))
    approved_script = sandbox_runner_script(
        approved_tools=approvals.approved_tools(first_run))
    denied_script = sandbox_runner_script(approved_tools=approvals.approved_tools(second_run))
    assert 'ALLOWED = set(["base32_decode","base64_decode","hex_decode","rot13_decode"])' in approved_script
    assert 'ALLOWED = set(["base32_decode","base64_decode","hex_decode"])' in denied_script

    approvals.record(first_run, "rot13_decode", decision="revoke", reviewer="operator",
                     expected_digest=capability_digest("rot13_decode"))
    assert approvals.approved_tools(first_run) == BASE_WORKFLOW_TOOLS
    with pytest.raises(sqlite3.IntegrityError, match="append-only"), sqlite3.connect(database) as db:
        db.execute("UPDATE workflow_capability_reviews SET decision='approve'")


def test_workflow_review_requires_existing_run_and_valid_operator_metadata(tmp_path):
    database = tmp_path / "state" / "metis.sqlite"
    approvals = WorkflowCapabilityApprovals(database)
    with pytest.raises(ValueError, match="existing run"):
        approvals.record("missing", "rot13_decode", decision="approve", reviewer="operator",
                         expected_digest=capability_digest("rot13_decode"))
    with pytest.raises(ValueError, match="existing run"):
        approvals.status("missing")
    source = tmp_path / "source.txt"
    source.write_bytes(b"fixture")
    run = CodexSession(database).intake(title="Workflow review", description="Local only",
                                        paths=[source], categories=["misc"])["run_id"]
    with pytest.raises(ValueError, match="reviewer identity"):
        approvals.record(run, "rot13_decode", decision="approve", reviewer="",
                         expected_digest=capability_digest("rot13_decode"))
    with pytest.raises(ValueError, match="unknown review-gated"):
        approvals.record(run, "shell", decision="approve", reviewer="operator", expected_digest="0" * 64)


def test_controller_validates_workflow_output_encoding_length_and_digest():
    output = b"decoded synthetic \x00\xff result"
    valid = {"schema_version": 1, "steps": 2, "output_bytes": len(output),
             "sha256": hashlib.sha256(output).hexdigest(),
             "output_b64": base64.b64encode(output).decode("ascii")}
    observed, decoded = _validate_workflow_output(json.dumps(valid), expected_steps=2)
    assert observed == valid and decoded == output

    with pytest.raises(ValueError, match="schema validation"):
        _validate_workflow_output(json.dumps({**valid, "output_bytes": MAX_WORKFLOW_OUTPUT + 1}),
                                  expected_steps=2)
    oversized = base64.b64encode(b"x" * (MAX_WORKFLOW_OUTPUT + 1)).decode("ascii")
    with pytest.raises(ValueError, match="length or encoding is invalid"):
        _validate_workflow_output(json.dumps({**valid, "output_b64": oversized}), expected_steps=2)
    with pytest.raises(ValueError, match="encoding is invalid"):
        _validate_workflow_output(json.dumps({**valid, "output_b64": "%%%"}), expected_steps=2)
    with pytest.raises(ValueError, match="digest mismatch"):
        _validate_workflow_output(json.dumps({**valid, "sha256": "0" * 64}), expected_steps=2)
    with pytest.raises(ValueError, match="schema validation"):
        _validate_workflow_output(json.dumps({**valid, "steps": True}), expected_steps=2)
    with pytest.raises(ValueError, match="schema validation"):
        _validate_workflow_output(json.dumps({**valid, "schema_version": True}), expected_steps=2)
    with pytest.raises(ValueError, match="schema validation"):
        _validate_workflow_output(json.dumps({**valid, "schema_version": 1.0}), expected_steps=2)


def test_corrupt_sandbox_output_is_not_registered_as_a_derived_artifact(tmp_path, monkeypatch):
    from metis.core.ctf_sandbox import Sandbox

    database = tmp_path / "state" / "metis.sqlite"
    configure(database, engine="docker", image="sha256:" + "a" * 64, platform=None)
    trial = generate_seeded_workflow(2)
    challenge = tmp_path / "challenge.txt"
    workflow = tmp_path / "workflow.json"
    challenge.write_bytes(trial.challenge)
    workflow.write_bytes(trial.workflow_json)
    session = CodexSession(database)
    created = session.intake(title="Corrupt output guard", description="Synthetic only",
                             paths=[challenge, workflow], categories=["misc"])
    artifacts_before = session.context(created["run_id"])["challenge"]["artifacts"]
    monkeypatch.setattr(Sandbox, "execute", lambda *args, **kwargs: {
        "ok": True, "stdout": {"text": "{\\\"corrupt\\\":true}"},
        "isolation": {"engine": "docker", "image": "sha256:" + "a" * 64,
                      "network": "none", "host_mounts": False}})
    result = run_workflow_in_sandbox(database, created["run_id"], target=artifacts_before[0],
                                     workflow_artifact=artifacts_before[1])
    assert result["ok"] is False
    assert "output_artifact" not in result
    assert session.context(created["run_id"])["challenge"]["artifacts"] == artifacts_before

    output = b"plausible but not isolated output"
    valid_worker_output = json.dumps({
        "schema_version": 1, "steps": 2, "output_bytes": len(output),
        "sha256": hashlib.sha256(output).hexdigest(),
        "output_b64": base64.b64encode(output).decode("ascii"),
    })
    monkeypatch.setattr(Sandbox, "execute", lambda *args, **kwargs: {
        "ok": True, "stdout": {"text": valid_worker_output},
        "isolation": {"engine": "docker", "image": "sha256:" + "a" * 64,
                      "network": "bridge", "host_mounts": True}})
    unisolated = run_workflow_in_sandbox(database, created["run_id"], target=artifacts_before[0],
                                         workflow_artifact=artifacts_before[1])
    assert unisolated["ok"] is False and "isolation" in unisolated["reason"]
    assert session.context(created["run_id"])["challenge"]["artifacts"] == artifacts_before


def test_external_digest_verifier_accepts_only_successful_matching_result():
    trial = generate_seeded_workflow(secrets.randbits(32))
    result = {"ok": True, "output_artifact": ".metis-derived/output.bin", "output_is_untrusted": True,
              "output_sha256": trial.oracle_sha256}
    assert verify_workflow_digest(result, trial.oracle_sha256)
    assert not verify_workflow_digest({**result, "ok": False}, trial.oracle_sha256)
    assert not verify_workflow_digest({**result, "output_artifact": None}, trial.oracle_sha256)
    assert not verify_workflow_digest({**result, "output_is_untrusted": False}, trial.oracle_sha256)
    assert not verify_workflow_digest({**result, "output_sha256": "0" * 64}, trial.oracle_sha256)
    with pytest.raises(ValueError, match="oracle commitment"):
        verify_workflow_digest({"ok": True}, "not-a-digest")


def test_replay_checks_isolation_result_and_oracle_without_leaking_output(monkeypatch, tmp_path):
    import metis.core.ctf_workflow as workflow_module

    digest = hashlib.sha256(b"private result").hexdigest()
    base = {"ok": True, "workflow_sha256": "a" * 64, "steps": 2,
            "output_bytes": 14, "output_sha256": digest,
            "output_artifact": ".metis-derived/private.bin", "output_is_untrusted": True,
            "sandbox": {"engine": "docker", "image": "sha256:" + "b" * 64,
                        "network": "none", "host_mounts": False}}
    calls = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        return dict(base)

    monkeypatch.setattr(workflow_module, "run_workflow_in_sandbox", runner)
    result = replay_workflow_in_sandbox(tmp_path / "db", "a" * 32,
                                        target="source.txt", workflow_artifact="workflow.json",
                                        oracle_sha256=digest)
    assert len(calls) == 2
    assert result == {"ok": True, "reproducible": True, "oracle_match": True,
                      "steps": 2, "output_bytes": 14, "reason": None}
    assert digest not in json.dumps(result)
    assert "private.bin" not in json.dumps(result)
    responses = iter((base, {**base, "sandbox": {**base["sandbox"], "image": "other"}}))
    monkeypatch.setattr(workflow_module, "run_workflow_in_sandbox",
                        lambda *args, **kwargs: next(responses))
    assert not replay_workflow_in_sandbox(tmp_path / "db", "a" * 32,
                                          target="source.txt", workflow_artifact="workflow.json")["reproducible"]


def test_replay_rejects_mismatch_or_failed_second_run(monkeypatch, tmp_path):
    import metis.core.ctf_workflow as workflow_module

    good = {"ok": True, "workflow_sha256": "a" * 64, "steps": 1,
            "output_bytes": 3, "output_sha256": "b" * 64,
            "output_artifact": "private", "output_is_untrusted": True,
            "sandbox": {"engine": "docker", "image": "sha256:" + "c" * 64,
                        "network": "none", "host_mounts": False}}
    responses = iter((good, {**good, "output_sha256": "d" * 64}))
    monkeypatch.setattr(workflow_module, "run_workflow_in_sandbox",
                        lambda *args, **kwargs: next(responses))
    result = replay_workflow_in_sandbox(tmp_path / "db", "a" * 32,
                                        target="source.txt", workflow_artifact="workflow.json")
    assert result["ok"] is False and result["reason"] == "sandbox runs differ"
    assert "output_sha256" not in result
    responses = iter((good, {"ok": False, "reason": "private worker detail"}))
    result = replay_workflow_in_sandbox(tmp_path / "db", "a" * 32,
                                        target="source.txt", workflow_artifact="workflow.json")
    assert result["reason"] == "second sandbox run failed"
    with pytest.raises(ValueError, match="oracle commitment"):
        replay_workflow_in_sandbox(tmp_path / "db", "a" * 32,
                                   target="source.txt", workflow_artifact="workflow.json",
                                   oracle_sha256="invalid")


def test_replay_cli_sanitizes_private_file_error_without_creating_state(monkeypatch, tmp_path, capsys):
    from metis.cli import main

    database = tmp_path / "missing.sqlite"
    private_path = tmp_path / "private-oracle-canary"
    monkeypatch.setattr(sys, "argv", ["metis", "workflow", "--database", str(database),
                                      "replay", "a" * 32, "--target", "source.txt",
                                      "--workflow-artifact", "workflow.json",
                                      "--oracle-sha256-file", str(private_path)])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "private-oracle-canary" not in captured.err
    assert not database.exists()


def test_replay_cli_oracle_exit_status(monkeypatch, tmp_path, capsys):
    from metis.cli import main

    output_digest = hashlib.sha256(b"private result").hexdigest()
    result = {"ok": True, "workflow_sha256": "a" * 64, "steps": 1,
              "output_bytes": 14, "output_sha256": output_digest,
              "output_artifact": ".metis-derived/private.bin",
              "output_is_untrusted": True,
              "sandbox": {"engine": "docker", "image": "sha256:" + "b" * 64,
                          "network": "none", "host_mounts": False}}
    monkeypatch.setattr(ctf_workflow, "run_workflow_in_sandbox",
                        lambda *args, **kwargs: dict(result))
    args = ["metis", "workflow", "--database", str(tmp_path / "state.sqlite"),
            "replay", "a" * 32, "--target", "source.txt",
            "--workflow-artifact", "workflow.json"]
    monkeypatch.setattr(sys, "argv", args)
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["oracle_match"] is None

    oracle = tmp_path / "private-oracle"
    oracle.write_text("0" * 64)
    monkeypatch.setattr(sys, "argv", args + ["--oracle-sha256-file", str(oracle)])
    assert main() == 2
    failed = json.loads(capsys.readouterr().out)
    assert failed["ok"] is False
    assert failed["reproducible"] is True
    assert failed["oracle_match"] is False
    assert output_digest not in json.dumps(failed)

    oracle.write_text(output_digest)
    assert main() == 0
    passed = json.loads(capsys.readouterr().out)
    assert passed["ok"] is True
    assert passed["oracle_match"] is True


def test_input_artifact_must_match_declared_target():
    candidate = WorkflowCandidate(input_artifact="challenge.txt", steps=[{"tool": "hex_decode"}])
    with pytest.raises(ValueError, match="selected declared artifact"):
        validate_workflow(candidate.model_dump_json(), input_artifact="other.txt")


@pytest.mark.skipif(not os.environ.get("METIS_TEST_SANDBOX_IMAGE"),
                    reason="requires an immutable METIS_TEST_SANDBOX_IMAGE")
def test_generated_workflow_runs_in_isolated_sandbox_and_passes_private_oracle(tmp_path):
    database = tmp_path / "state" / "metis.sqlite"
    configure(database, engine="docker", image=os.environ["METIS_TEST_SANDBOX_IMAGE"],
              platform=os.environ.get("METIS_TEST_SANDBOX_PLATFORM"))
    trial = generate_seeded_workflow(secrets.randbits(32))
    challenge = tmp_path / "challenge.txt"
    workflow = tmp_path / "workflow.json"
    challenge.write_bytes(trial.challenge)
    workflow.write_bytes(trial.workflow_json)
    session = CodexSession(database)
    created = session.intake(title="Generated workflow integration", description="Offline local fixture.",
                             paths=[challenge, workflow], categories=["misc"], max_actions=8,
                             wall_seconds=120, evaluation_split="practice")
    artifacts = session.context(created["run_id"])["challenge"]["artifacts"]
    registry_before = frozenset(ARTIFACT_TOOLS)
    verifier_before = verify_workflow_digest.__code__.co_code
    result = run_workflow_in_sandbox(database, created["run_id"], target=artifacts[0],
                                     workflow_artifact=artifacts[1], timeout=20)
    assert verify_workflow_digest(result, trial.oracle_sha256)
    root = session.artifact_root(created["run_id"])
    assert root is not None
    output = read_artifact(root, result["output_artifact"], max_bytes=MAX_WORKFLOW_OUTPUT)
    assert hashlib.sha256(output).hexdigest() == result["output_sha256"]
    assert len(output) == result["output_bytes"] == 29
    assert result["output_is_untrusted"] is True
    assert result["output_artifact"] in session.context(created["run_id"])["challenge"]["artifacts"]
    assert trial.oracle_sha256 not in session.store.export_jsonl(created["run_id"])
    assert result["sandbox"]["network"] == "none"
    assert result["sandbox"]["host_mounts"] is False
    repeated = replay_workflow_in_sandbox(database, created["run_id"], target=artifacts[0],
                                           workflow_artifact=artifacts[1],
                                           oracle_sha256=trial.oracle_sha256)
    assert repeated["ok"] is True and repeated["oracle_match"] is True
    assert repeated["output_bytes"] == 29
    assert trial.oracle_sha256 not in json.dumps(repeated)
    assert frozenset(ARTIFACT_TOOLS) == registry_before
    assert verify_workflow_digest.__code__.co_code == verifier_before


@pytest.mark.skipif(not os.environ.get("METIS_TEST_SANDBOX_IMAGE"),
                    reason="requires an immutable METIS_TEST_SANDBOX_IMAGE")
def test_reviewed_rot13_capability_runs_only_after_run_scoped_approval(tmp_path):
    database = tmp_path / "state" / "metis.sqlite"
    configure(database, engine="docker", image=os.environ["METIS_TEST_SANDBOX_IMAGE"],
              platform=os.environ.get("METIS_TEST_SANDBOX_PLATFORM"))
    answer = b"CTF{reviewed_builtin_transform}"
    encoded = answer.translate(bytes.maketrans(
        b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        b"NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm"))
    challenge = tmp_path / "challenge.txt"
    workflow = tmp_path / "workflow.json"
    challenge.write_bytes(encoded)
    workflow.write_text(json.dumps({"schema_version": 1, "input_artifact": "challenge.txt",
                                    "steps": [{"tool": "rot13_decode"}]}))
    session = CodexSession(database)
    created = session.intake(title="Reviewed workflow capability", description="Synthetic local fixture",
                             paths=[challenge, workflow], categories=["misc"], max_actions=8,
                             wall_seconds=120, evaluation_split="practice")
    run_id = created["run_id"]
    artifacts = session.context(run_id)["challenge"]["artifacts"]
    approvals = WorkflowCapabilityApprovals(database)
    registry_before = frozenset(ARTIFACT_TOOLS)
    verifier_before = verify_workflow_digest.__code__.co_code
    with pytest.raises(ValueError, match="unregistered tool"):
        run_workflow_in_sandbox(database, run_id, target=artifacts[0], workflow_artifact=artifacts[1])
    approvals.record(run_id, "rot13_decode", decision="approve", reviewer="test-operator",
                     expected_digest=capability_digest("rot13_decode"))
    result = run_workflow_in_sandbox(database, run_id, target=artifacts[0],
                                     workflow_artifact=artifacts[1], timeout=20)
    assert verify_workflow_digest(result, hashlib.sha256(answer).hexdigest())
    assert result["sandbox"]["network"] == "none"
    assert result["sandbox"]["host_mounts"] is False
    assert result["output_is_untrusted"] is True
    assert frozenset(ARTIFACT_TOOLS) == registry_before
    assert verify_workflow_digest.__code__.co_code == verifier_before
