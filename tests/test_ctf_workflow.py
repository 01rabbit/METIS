"""Bounded declarative workflows cannot add tools, policy, verifier or code."""
import json
import os
import secrets

import pytest

from metis.core.codex_session import CodexSession
from metis.core.ctf_artifacts import ARTIFACT_TOOLS
from metis.core.ctf_sandbox import configure
from metis.core.ctf_workflow import (
    WorkflowCandidate,
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


def test_sandbox_runner_is_fixed_allowlisted_and_digest_only():
    script = sandbox_runner_script()
    assert "ALLOWED = {\"base32_decode\", \"base64_decode\", \"hex_decode\"}" in script
    assert "hashlib.sha256(value).hexdigest()" in script
    assert "output_bytes" in script
    assert "print(value" not in script
    assert "subprocess" not in script
    assert "socket" not in script
    assert {"base32_decode", "base64_decode", "hex_decode"} <= ARTIFACT_TOOLS


def test_external_digest_verifier_accepts_only_successful_matching_result():
    trial = generate_seeded_workflow(secrets.randbits(32))
    assert verify_workflow_digest({"ok": True, "output_sha256": trial.oracle_sha256}, trial.oracle_sha256)
    assert not verify_workflow_digest({"ok": False, "output_sha256": trial.oracle_sha256}, trial.oracle_sha256)
    assert not verify_workflow_digest({"ok": True, "output_sha256": "0" * 64}, trial.oracle_sha256)
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
    assert result["sandbox"]["network"] == "none"
    assert result["sandbox"]["host_mounts"] is False
    assert frozenset(ARTIFACT_TOOLS) == registry_before
    assert verify_workflow_digest.__code__.co_code == verifier_before
