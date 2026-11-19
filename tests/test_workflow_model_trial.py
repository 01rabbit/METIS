"""The model proposal never expands workflow capability or scope."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from metis.core import workflow_model_trial
from metis.core.codex_isolation import sandbox_command, seatbelt_profile
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
    tmp_path.chmod(0o700)
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
    database = tmp_path / "run-workspace" / "state.sqlite"

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
    ("public oracle directory", "owner-only directory"),
    ("invalid platform", "unsupported platform"),
    ("oracle as fixture", "exposes the oracle"),
    ("plaintext as fixture", "exposes the oracle"),
    ("invalid image", "immutable SHA-256"),
])
def test_external_trial_fails_closed_before_proposer(tmp_path, external_fixture, invalid, message):
    challenge, oracle, trial = external_fixture
    image = "sha256:" + "a" * 64
    platform = None
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
    elif invalid == "public oracle directory":
        tmp_path.chmod(0o755)
    elif invalid == "oracle as fixture":
        challenge.write_text(trial.oracle_sha256)
    elif invalid == "plaintext as fixture":
        challenge.write_bytes(b"Example")
        oracle.write_text(hashlib.sha256(b"Example").hexdigest())
    elif invalid == "invalid platform":
        platform = "not-a-platform"
    elif invalid == "invalid image":
        image = "sha256:" + "x" * 64

    def unexpected_proposal(_):
        pytest.fail("invalid intake reached the proposer")

    with pytest.raises(ValueError, match=message) as error:
        run_external_fixture_trial(tmp_path / "new-run" / "state.sqlite", image=image, platform=platform,
                                   fixture=challenge, oracle=oracle, proposer=unexpected_proposal)
    assert trial.oracle_sha256 not in str(error.value)
    assert not (tmp_path / "new-run").exists()


@pytest.mark.parametrize("collision", ["oracle", "symlink", "checkout", "reserved database name"])
def test_external_trial_run_directory_cannot_overwrite_inputs_or_write_to_checkout(
    tmp_path, external_fixture, collision,
):
    fixture, oracle, trial = external_fixture
    workspace = tmp_path / "workspace"
    database = workspace / "state.sqlite"
    if collision == "oracle":
        oracle = oracle.rename(tmp_path / "sandbox.json")
        database = tmp_path / "state.sqlite"
    elif collision == "symlink":
        workspace.mkdir()
        (workspace / "sandbox.json").symlink_to(oracle)
    elif collision == "checkout":
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        (checkout / ".git").touch()
        database = checkout / "new-run" / "state.sqlite"
    else:
        database = workspace / "SaNdBoX.JsOn"

    with pytest.raises(ValueError, match="private run directory|outside Git checkouts"):
        run_external_fixture_trial(database, image="sha256:" + "a" * 64, platform=None,
                                   fixture=fixture, oracle=oracle,
                                   proposer=lambda _: pytest.fail("invalid workspace reached model"))
    assert oracle.read_text().strip() == trial.oracle_sha256
    assert not database.exists()


def test_default_external_proposer_receives_canonical_protected_directory(
    tmp_path, external_fixture, monkeypatch,
):
    fixture, oracle, trial = external_fixture
    alias = tmp_path / "alias"
    alias.symlink_to(oracle.parent, target_is_directory=True)
    seen = []

    def propose(challenge, *, oracle_directory):
        seen.append((challenge, oracle_directory))
        raise RuntimeError("stop before replay")

    monkeypatch.setattr(workflow_model_trial, "codex_proposer", propose)
    with pytest.raises(RuntimeError, match="stop before replay"):
        run_external_fixture_trial(tmp_path / "run-workspace" / "state.sqlite",
                                   image="sha256:" + "a" * 64, platform=None,
                                   fixture=fixture, oracle=alias / oracle.name)
    assert seen == [(trial.challenge, oracle.parent.resolve())]
    assert (tmp_path / "run-workspace").stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize(("program", "timeout", "output_limit", "passes"), [
    ("import time; time.sleep(10)", 0.1, 65_536, False),
    (
        ("import os, sys\n"
        "os.write(1, b'x' * 50000)\n"
        "assert len(os.read(0, 1)) == 1\n"
        "assert len(sys.stdin.buffer.read()) == 65535"),
        5, 65_536, True,
    ),
    ("import os; os.write(2, b'x' * 50000)", 5, 4096, False),
])
def test_proposal_pipe_exchange_enforces_deadline_and_output_bound(
    program, timeout, output_limit, passes,
):
    with subprocess.Popen([sys.executable, "-c", program], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        if passes:
            workflow_model_trial._exchange_proposal(
                process, b"x" * 65_536, timeout=timeout, output_limit=output_limit,
            )
            assert process.returncode == 0
        else:
            with pytest.raises(RuntimeError, match="unavailable, timed out, or exceeded"):
                workflow_model_trial._exchange_proposal(
                    process, b"x" * 65_536, timeout=timeout, output_limit=output_limit,
                )
            assert process.returncode is not None


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("sandbox-exec"),
                    reason="requires macOS Seatbelt")
def test_oracle_directory_is_denied_by_applied_seatbelt_profile(tmp_path, external_fixture):
    fixture, oracle, _ = external_fixture
    turn_dir = tmp_path / "turn"
    turn_dir.mkdir()
    permission_prompt = turn_dir / "challenge.txt"
    permission_prompt.write_bytes(fixture.read_bytes())
    cat = shutil.which("cat")
    assert cat is not None
    executable = Path(cat)
    profile = turn_dir / "profile.sb"
    profile.write_text(seatbelt_profile(turn_dir=turn_dir, readable=[],
                                        protected=[oracle.parent.resolve()], proxy_port=1,
                                        executable=executable))
    read_fixture = subprocess.run(sandbox_command(profile, [cat, str(permission_prompt)]),
                                  capture_output=True, timeout=5, check=True)
    assert read_fixture.stdout == fixture.read_bytes()
    read_oracle = subprocess.run(sandbox_command(profile, [cat, str(oracle)]),
                                 capture_output=True, timeout=5, check=False)
    assert read_oracle.returncode != 0
    assert not read_oracle.stdout


@pytest.mark.parametrize("untrusted_path", ["oracle", "run"])
def test_external_trial_rejects_nonsticky_writable_ancestor(
    tmp_path, external_fixture, untrusted_path,
):
    fixture, oracle, _ = external_fixture
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    private = shared / "private"
    private.mkdir(mode=0o700)
    workspace_parent = tmp_path
    if untrusted_path == "oracle":
        oracle = oracle.rename(private / oracle.name)
    else:
        workspace_parent = private
    workspace = workspace_parent / "run-workspace"
    with pytest.raises(ValueError, match="trusted directory ancestry"):
        run_external_fixture_trial(workspace / "state.sqlite", image="sha256:" + "a" * 64,
                                   platform=None, fixture=fixture, oracle=oracle,
                                   proposer=lambda _: pytest.fail("unsafe path reached proposer"))
    assert not workspace.exists()


def test_external_trial_accepts_sticky_shared_path_with_trusted_owners(
    tmp_path, external_fixture,
):
    fixture, oracle, _ = external_fixture
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o1777)
    private = shared / "private"
    private.mkdir(mode=0o700)
    oracle = oracle.rename(private / oracle.name)

    def propose(_):
        raise RuntimeError("stop before replay")

    with pytest.raises(RuntimeError, match="stop before replay"):
        run_external_fixture_trial(private / "run-workspace" / "state.sqlite",
                                   image="sha256:" + "a" * 64, platform=None,
                                   fixture=fixture, oracle=oracle, proposer=propose)


@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS extended ACLs")
@pytest.mark.parametrize("acl_target", ["oracle file", "oracle ancestor", "workspace ancestor"])
def test_external_trial_rejects_macos_acl_grants_despite_private_mode(
    tmp_path, external_fixture, acl_target,
):
    fixture, oracle, _ = external_fixture
    run_parent = tmp_path
    if acl_target == "oracle file":
        target = oracle
        entry = "everyone allow read"
    elif acl_target == "oracle ancestor":
        target = tmp_path / "oracle-ancestor"
        target.mkdir(mode=0o755)
        private = target / "private"
        private.mkdir(mode=0o700)
        oracle = oracle.rename(private / oracle.name)
        entry = "everyone allow add_file,delete_child"
    else:
        target = tmp_path / "run-ancestor"
        target.mkdir(mode=0o755)
        run_parent = target
        entry = "everyone allow add_file,delete_child"

    subprocess.run(["/bin/chmod", "+a", entry, target], check=True, timeout=5)
    try:
        assert target.stat().st_mode & 0o022 == 0
        workspace = run_parent / "run-workspace"
        with pytest.raises(ValueError, match="must have no extended ACL grants"):
            run_external_fixture_trial(workspace / "state.sqlite", image="sha256:" + "a" * 64,
                                       platform=None, fixture=fixture, oracle=oracle,
                                       proposer=lambda _: pytest.fail("ACL grant reached proposer"))
        assert not workspace.exists()
    finally:
        subprocess.run(["/bin/chmod", "-a", entry, target], check=True, timeout=5)


@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS extended ACLs")
def test_external_trial_accepts_mac_deny_only_acl(tmp_path, external_fixture):
    fixture, oracle, _ = external_fixture
    protected = tmp_path / "run-parent"
    protected.mkdir(mode=0o700)

    def propose(_):
        raise RuntimeError("stop before replay")

    entry = "everyone deny delete"
    subprocess.run(["/bin/chmod", "+a", entry, protected], check=True, timeout=5)
    try:
        with pytest.raises(RuntimeError, match="stop before replay"):
            run_external_fixture_trial(protected / "run-workspace" / "state.sqlite",
                                       image="sha256:" + "a" * 64, platform=None,
                                       fixture=fixture, oracle=oracle, proposer=propose)
    finally:
        subprocess.run(["/bin/chmod", "-a", entry, protected], check=True, timeout=5)
