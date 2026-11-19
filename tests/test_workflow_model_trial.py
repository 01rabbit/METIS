"""The model proposal never expands workflow capability or scope."""
import hashlib
import json
import os

import pytest

from metis.core import workflow_model_trial
from metis.core.codex_session import CodexSession
from metis.core.ctf_sandbox import configure
from metis.core.ctf_workflow import (
    MAX_WORKFLOW_INPUT,
    _validate_digest_only_output,
    generate_seeded_workflow,
    replay_workflow_in_sandbox,
    sandbox_runner_script,
)
from metis.core.workflow_model_trial import run_external_fixture_trial, run_unseen_trial


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


@pytest.fixture
def external_fixture(tmp_path):
    challenge = tmp_path / "external-encoding.txt"
    oracle = tmp_path / "independent.sha256"
    trial = generate_seeded_workflow(3)
    challenge.write_bytes(trial.challenge)
    oracle.write_text(trial.oracle_sha256 + "\n")
    oracle.chmod(0o600)
    return challenge, oracle, trial


@pytest.mark.parametrize("matched", [True, False, None])
def test_external_trial_snapshots_inputs_and_projects_only_safe_results(
    tmp_path, monkeypatch, external_fixture, matched,
):
    challenge, oracle, trial = external_fixture
    database = tmp_path / "state.sqlite"

    def propose(challenge_bytes):
        assert challenge_bytes == trial.challenge
        challenge.write_bytes(b"AAAA")
        oracle.write_text("a" * 64)
        return trial.workflow_json

    def replay(replay_db, run_id, *, target, workflow_artifact, oracle_sha256, digest_only):
        assert replay_db == database
        assert digest_only is True
        assert oracle_sha256 == trial.oracle_sha256
        session = CodexSession(database)
        root = session.artifact_root(run_id)
        assert root is not None
        assert (root / target).read_bytes() == trial.challenge
        assert (root / workflow_artifact).is_file()
        assert len(list(root.iterdir())) == 2
        assert oracle.name not in session.store.export_jsonl(run_id)
        assert trial.oracle_sha256 not in session.store.export_jsonl(run_id)
        result = {"ok": matched is True, "reproducible": matched is not None}
        if matched is not None:
            result["oracle_match"] = matched
        return result

    monkeypatch.setattr(workflow_model_trial, "replay_workflow_in_sandbox", replay)
    result = run_external_fixture_trial(database, image="sha256:" + "a" * 64, platform=None,
                                        fixture=challenge, oracle=oracle, proposer=propose)
    assert result["ok"] is (matched is True)
    assert result["oracle_match"] is matched
    assert result["fixture_sha256"] == hashlib.sha256(trial.challenge).hexdigest()
    assert trial.oracle_sha256 not in json.dumps(result)


@pytest.mark.parametrize(("invalid", "message"), [
    ("oversize", "size bounds"),
    ("invalid alphabet", "ASCII encoding token"),
    ("symlink fixture", "could not be read"),
    ("fifo fixture", "regular file"),
    ("malformed oracle", "one lowercase SHA-256"),
    ("public oracle", "private file"),
    ("linked oracle", "private file"),
    ("oracle in checkout", "outside Git checkouts"),
    ("oracle as fixture", "exposes the oracle"),
    ("plaintext as fixture", "exposes the oracle"),
    ("invalid image", "immutable SHA-256"),
])
def test_external_trial_fails_closed_before_proposer(tmp_path, external_fixture, invalid, message):
    challenge, oracle, trial = external_fixture
    image = "sha256:" + "a" * 64
    if invalid == "oversize":
        challenge.write_bytes(b"A" * (MAX_WORKFLOW_INPUT + 1))
    elif invalid == "invalid alphabet":
        challenge.write_bytes(b"https://example.invalid")
    elif invalid == "symlink fixture":
        challenge.unlink()
        challenge.symlink_to(oracle)
    elif invalid == "fifo fixture":
        challenge.unlink()
        os.mkfifo(challenge)
    elif invalid == "malformed oracle":
        oracle.write_text("not a digest")
    elif invalid == "public oracle":
        oracle.chmod(0o644)
    elif invalid == "linked oracle":
        os.link(oracle, tmp_path / "hardlink.sha256")
    elif invalid == "oracle in checkout":
        (tmp_path / ".git").touch()
    elif invalid == "oracle as fixture":
        challenge.write_text(trial.oracle_sha256)
    elif invalid == "plaintext as fixture":
        challenge.write_bytes(b"Example")
        oracle.write_text(hashlib.sha256(b"Example").hexdigest())
    elif invalid == "invalid image":
        image = "sha256:" + "x" * 64

    def unexpected_proposal(_):
        pytest.fail("invalid intake reached the proposer")

    with pytest.raises(ValueError, match=message) as error:
        run_external_fixture_trial(tmp_path / "state.sqlite", image=image, platform=None,
                                   fixture=challenge, oracle=oracle, proposer=unexpected_proposal)
    assert trial.oracle_sha256 not in str(error.value)
    assert not (tmp_path / "state.sqlite").exists()
