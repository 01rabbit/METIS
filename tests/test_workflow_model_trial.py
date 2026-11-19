"""The model proposal never expands workflow capability or scope."""
import json
import os

import pytest

from metis.core.codex_session import CodexSession
from metis.core.ctf_sandbox import configure
from metis.core.ctf_workflow import (
    _validate_digest_only_output,
    generate_seeded_workflow,
    replay_workflow_in_sandbox,
    sandbox_runner_script,
)
from metis.core.workflow_model_trial import run_unseen_trial


@pytest.mark.parametrize("change", [
    {"steps": [{"tool": "shell"}]},
    {"steps": [{"tool": "rot13_decode"}]},
    {"policy": "allow-all"},
    {"verifier": "accept"},
    {"code": "print(1)"},
])
def test_model_proposal_cannot_extend_tools_policy_or_verifier(tmp_path, change):
    proposal = {"schema_version": 1, "input_artifact": "challenge.txt",
                "steps": [{"tool": "base64_decode"}], **change}
    with pytest.raises(ValueError, match="fixed schema|unregistered tool"):
        run_unseen_trial(tmp_path / "state.sqlite", image="sha256:" + "a" * 64,
                         platform=None, seeds=(2, 3),
                         proposer=lambda _: json.dumps(proposal).encode())


def test_trial_requires_two_distinct_families(tmp_path):
    with pytest.raises(ValueError, match="distinct seeds"):
        run_unseen_trial(tmp_path / "state.sqlite", image="sha256:" + "a" * 64,
                         platform=None, seeds=(2, 4), proposer=lambda _: b"{}")
    assert not (tmp_path / "state.sqlite").exists()


def test_digest_only_runner_cannot_emit_answer_bytes():
    script = sandbox_runner_script(digest_only=True)
    assert "if not True:" in script
    metadata = {"schema_version": 1, "steps": 2, "output_bytes": 29,
                "input_sha256": "a" * 64, "sha256": "b" * 64}
    assert _validate_digest_only_output(json.dumps(metadata), expected_steps=2) == metadata
    with pytest.raises(ValueError, match="schema"):
        _validate_digest_only_output(json.dumps({**metadata, "output_b64": "hidden"}), expected_steps=2)


@pytest.mark.skipif(not os.environ.get("METIS_TEST_SANDBOX_IMAGE"),
                    reason="requires an immutable METIS_TEST_SANDBOX_IMAGE")
def test_private_oracle_replay_registers_no_decoded_artifact(tmp_path):
    database = tmp_path / "state.sqlite"
    configure(database, engine="docker", image=os.environ["METIS_TEST_SANDBOX_IMAGE"],
              platform=os.environ.get("METIS_TEST_SANDBOX_PLATFORM"))
    trial = generate_seeded_workflow(2)
    challenge = tmp_path / "challenge.txt"
    workflow = tmp_path / "workflow.json"
    challenge.write_bytes(trial.challenge)
    workflow.write_bytes(trial.workflow_json)
    session = CodexSession(database)
    created = session.intake(title="Digest-only trial", description="Offline local fixture",
                             paths=[challenge, workflow], categories=["misc"])
    run_id = created["run_id"]
    before = session.context(run_id)["challenge"]["artifacts"]
    result = replay_workflow_in_sandbox(database, run_id, target=before[0],
                                        workflow_artifact=before[1],
                                        oracle_sha256=trial.oracle_sha256, digest_only=True)
    assert result["ok"] and result["reproducible"] and result["oracle_match"]
    assert session.context(run_id)["challenge"]["artifacts"] == before
    root = session.artifact_root(run_id)
    assert root is not None and not list(root.rglob(".metis-derived/*"))
    assert trial.oracle_sha256 not in session.store.export_jsonl(run_id)
