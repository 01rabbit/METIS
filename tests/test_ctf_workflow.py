"""Bounded declarative workflows cannot add tools, policy, verifier or code."""
import base64
import hashlib
import json
import os
import secrets

import pytest

from metis.core.artifacts import read_artifact
from metis.core.codex_session import CodexSession
from metis.core.ctf_artifacts import ARTIFACT_TOOLS
from metis.core.ctf_sandbox import configure
from metis.core.ctf_workflow import (
    MAX_WORKFLOW_OUTPUT,
    WorkflowCandidate,
    _validate_workflow_output,
    generate_seeded_workflow,
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


def test_sandbox_runner_is_fixed_allowlisted_and_returns_bounded_output():
    script = sandbox_runner_script()
    assert "ALLOWED = {\"base32_decode\", \"base64_decode\", \"hex_decode\"}" in script
    assert "hashlib.sha256(value).hexdigest()" in script
    assert "output_bytes" in script
    assert "MAX_OUTPUT_BYTES = 16384" in script
    assert "output_b64" in script
    assert "subprocess" not in script
    assert "socket" not in script
    assert {"base32_decode", "base64_decode", "hex_decode"} <= ARTIFACT_TOOLS


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
    assert frozenset(ARTIFACT_TOOLS) == registry_before
    assert verify_workflow_digest.__code__.co_code == verifier_before
