"""The model proposal never expands workflow capability or scope."""
import base64
import hashlib
import importlib.util
import json
import os
import secrets
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
from metis.core.workflow_model_trial import (
    MAX_TRIAL_CASES,
    MAX_TRIAL_MANIFEST_BYTES,
    run_external_fixture_manifest_trial,
    run_external_fixture_trial,
    run_unseen_trial,
)

_CLI_SPEC = importlib.util.spec_from_file_location(
    "issue7_unseen_trial_cli", Path(__file__).parents[1] / "scripts" / "issue7_unseen_trial.py",
)
assert _CLI_SPEC is not None and _CLI_SPEC.loader is not None
unseen_trial_cli = importlib.util.module_from_spec(_CLI_SPEC)
_CLI_SPEC.loader.exec_module(unseen_trial_cli)


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


def _write_trial_manifest(root, cases):
    path = root / "trial.json"
    path.write_text(json.dumps({"schema_version": 1, "cases": cases}))
    path.chmod(0o600)
    return path


def _manifest_case(root, case_id, seed):
    trial = generate_seeded_workflow(seed)
    fixture_name, oracle_name = f"{case_id}.txt", f"{case_id}.sha256"
    (root / fixture_name).write_bytes(trial.challenge)
    oracle = root / oracle_name
    oracle.write_text(trial.oracle_sha256 + "\n")
    oracle.chmod(0o600)
    return {"case_id": case_id, "fixture": fixture_name, "oracle": oracle_name}, trial


def test_manifest_snapshots_all_cases_sorts_ids_and_projects_answer_free_results(
    tmp_path, monkeypatch,
):
    tmp_path.chmod(0o700)
    second, trial_b = _manifest_case(tmp_path, "beta", 3)
    first, trial_a = _manifest_case(tmp_path, "alpha", 2)
    manifest = _write_trial_manifest(tmp_path, [second, first])
    database = tmp_path / "runs" / "state.sqlite"
    replayed = []
    run_ids = []

    def replay(replay_db, run_id, *, target, workflow_artifact, oracle_sha256, digest_only):
        replayed.append(oracle_sha256)
        run_ids.append(run_id)
        assert digest_only
        return {"ok": oracle_sha256 in {trial_a.oracle_sha256, trial_b.oracle_sha256},
                "reproducible": True, "oracle_match": True,
                "output_b64": "decoded-private-answer", "private_path": str(tmp_path)}

    monkeypatch.setattr(workflow_model_trial, "replay_workflow_in_sandbox", replay)
    result = run_external_fixture_manifest_trial(
        database, image="sha256:" + "a" * 64, platform=None, manifest=manifest,
        proposer=lambda challenge: trial_a.workflow_json if challenge == trial_a.challenge
        else trial_b.workflow_json,
    )
    assert [row["case_id"] for row in result["cases"]] == ["alpha", "beta"]
    assert result["summary"] == {"total": 2, "passed": 2, "failed": 0, "pass_rate": 1.0}
    assert len(replayed) == 2
    serialized = json.dumps(result)
    assert trial_a.oracle_sha256 not in serialized and trial_b.oracle_sha256 not in serialized
    assert str(tmp_path) not in serialized and "decoded-private-answer" not in serialized
    for run_id in [row.get("run_id") for row in result["cases"]]:
        assert run_id is None
    session = CodexSession(database)
    event_data = "".join(session.store.export_jsonl(run_id) for run_id in run_ids)
    assert trial_a.oracle_sha256 not in event_data and trial_b.oracle_sha256 not in event_data
    assert str(tmp_path) not in event_data and "decoded-private-answer" not in event_data


@pytest.mark.parametrize("invalid", [
    "malformed", "oversized", "too-many", "duplicate-id", "duplicate-path", "unsafe-path",
])
def test_invalid_manifest_fails_before_proposer_or_run_side_effects(tmp_path, monkeypatch, invalid):
    tmp_path.chmod(0o700)
    case, _ = _manifest_case(tmp_path, "alpha", 2)
    cases = [case]
    manifest = _write_trial_manifest(tmp_path, cases)
    if invalid == "malformed":
        manifest.write_text('{"schema_version":1,"cases":[}')
    elif invalid == "oversized":
        manifest.write_bytes(b" " * (MAX_TRIAL_MANIFEST_BYTES + 1))
    elif invalid == "too-many":
        cases = [{"case_id": f"c{i}", "fixture": f"f{i}.txt", "oracle": f"o{i}.sha256"}
                 for i in range(MAX_TRIAL_CASES + 1)]
        manifest = _write_trial_manifest(tmp_path, cases)
    elif invalid == "duplicate-id":
        manifest = _write_trial_manifest(tmp_path, [case, {**case, "fixture": "other.txt",
                                                           "oracle": "other.sha256"}])
    elif invalid == "duplicate-path":
        manifest = _write_trial_manifest(tmp_path, [case, {"case_id": "beta",
                                                           "fixture": case["fixture"],
                                                           "oracle": "other.sha256"}])
    elif invalid == "unsafe-path":
        manifest = _write_trial_manifest(tmp_path, [{**case, "fixture": "../secret.txt"}])

    proposer_called = False
    configure_called = False

    def proposer(_):
        nonlocal proposer_called
        proposer_called = True
        return b"{}"

    def configure(*args, **kwargs):
        nonlocal configure_called
        configure_called = True

    monkeypatch.setattr(workflow_model_trial, "configure", configure)
    with pytest.raises(ValueError):
        run_external_fixture_manifest_trial(
            tmp_path / "runs" / "state.sqlite", image="sha256:" + "a" * 64,
            platform=None, manifest=manifest, proposer=proposer,
        )
    assert not proposer_called and not configure_called
    assert not (tmp_path / "runs").exists()


def test_manifest_failure_accounting_keeps_denominator(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    alpha, trial_a = _manifest_case(tmp_path, "alpha", 2)
    beta, trial_b = _manifest_case(tmp_path, "beta", 3)
    manifest = _write_trial_manifest(tmp_path, [alpha, beta])
    monkeypatch.setattr(workflow_model_trial, "replay_workflow_in_sandbox",
                        lambda *args, **kwargs: {"ok": False, "reproducible": False})
    result = run_external_fixture_manifest_trial(
        tmp_path / "runs" / "state.sqlite", image="sha256:" + "a" * 64,
        platform=None, manifest=manifest,
        proposer=lambda challenge: trial_a.workflow_json if challenge == trial_a.challenge
        else trial_b.workflow_json,
    )
    assert result["summary"] == {"total": 2, "passed": 0, "failed": 2, "pass_rate": 0.0}
    assert all(row["failure"] == "replay" for row in result["cases"])


def test_manifest_validates_later_oracle_before_first_proposer_or_workspace(tmp_path):
    tmp_path.chmod(0o700)
    alpha, _ = _manifest_case(tmp_path, "alpha", 2)
    beta, _ = _manifest_case(tmp_path, "beta", 3)
    (tmp_path / beta["oracle"]).write_text("invalid")
    manifest = _write_trial_manifest(tmp_path, [alpha, beta])
    proposer_called = False

    def proposer(_):
        nonlocal proposer_called
        proposer_called = True
        return b"{}"

    with pytest.raises(ValueError, match="one lowercase SHA-256"):
        run_external_fixture_manifest_trial(
            tmp_path / "runs" / "state.sqlite", image="sha256:" + "a" * 64,
            platform=None, manifest=manifest, proposer=proposer,
        )
    assert not proposer_called and not (tmp_path / "runs").exists()


def test_manifest_rejects_duplicate_fixture_bytes_before_any_run(tmp_path):
    tmp_path.chmod(0o700)
    alpha, trial = _manifest_case(tmp_path, "alpha", 2)
    beta, _ = _manifest_case(tmp_path, "beta", 3)
    (tmp_path / beta["fixture"]).write_bytes(trial.challenge)
    manifest = _write_trial_manifest(tmp_path, [alpha, beta])
    proposer_called = False

    def proposer(_):
        nonlocal proposer_called
        proposer_called = True
        return b"{}"

    with pytest.raises(ValueError, match="duplicate fixture content"):
        run_external_fixture_manifest_trial(
            tmp_path / "runs" / "state.sqlite", image="sha256:" + "a" * 64,
            platform=None, manifest=manifest, proposer=proposer,
        )
    assert not proposer_called and not (tmp_path / "runs").exists()


def test_manifest_rejects_fixture_containing_another_case_oracle_digest(tmp_path):
    tmp_path.chmod(0o700)
    alpha, _ = _manifest_case(tmp_path, "alpha", 2)
    beta, trial_b = _manifest_case(tmp_path, "beta", 3)
    (tmp_path / alpha["fixture"]).write_bytes(
        b"x" + trial_b.oracle_sha256.encode("ascii") + b"y",
    )
    manifest = _write_trial_manifest(tmp_path, [alpha, beta])
    proposer_called = False

    def proposer(_):
        nonlocal proposer_called
        proposer_called = True
        return b"{}"

    with pytest.raises(ValueError, match="exposes a case oracle commitment"):
        run_external_fixture_manifest_trial(
            tmp_path / "runs" / "state.sqlite", image="sha256:" + "a" * 64,
            platform=None, manifest=manifest, proposer=proposer,
        )
    assert not proposer_called and not (tmp_path / "runs").exists()


def test_manifest_accepts_maximum_cases_with_deterministic_order(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    cases = []
    for index in range(MAX_TRIAL_CASES):
        case, _ = _manifest_case(tmp_path, f"case-{index:02}", index)
        cases.append(case)
    manifest = _write_trial_manifest(tmp_path, list(reversed(cases)))
    monkeypatch.setattr(workflow_model_trial, "configure", lambda *args, **kwargs: None)
    executed = []

    def run_fixture(database, fixture, plan, *, index):
        executed.append((index, plan.steps[0].tool))
        return {"ok": True, "reproducible": True, "oracle_match": True,
                "selected_steps": [step.tool for step in plan.steps]}

    monkeypatch.setattr(workflow_model_trial, "_execute_workflow", run_fixture)
    results = {hashlib.sha256(generate_seeded_workflow(seed).challenge).hexdigest():
               generate_seeded_workflow(seed).workflow_json
               for seed in range(MAX_TRIAL_CASES)}
    result = run_external_fixture_manifest_trial(
        tmp_path / "runs" / "state.sqlite", image="sha256:" + "a" * 64,
        platform=None, manifest=manifest,
        proposer=lambda challenge: results[hashlib.sha256(challenge).hexdigest()],
    )
    assert result["summary"]["total"] == MAX_TRIAL_CASES
    assert result["summary"]["passed"] == MAX_TRIAL_CASES
    assert [row["case_id"] for row in result["cases"]] == sorted(
        case["case_id"] for case in cases
    )
    assert [index for index, _ in executed] == list(range(1, MAX_TRIAL_CASES + 1))


def test_manifest_sanitizes_proposer_infrastructure_failure(tmp_path):
    tmp_path.chmod(0o700)
    case, trial = _manifest_case(tmp_path, "stable-case", 2)
    manifest = _write_trial_manifest(tmp_path, [case])
    private_path = str(tmp_path / case["oracle"])

    def fail_proposal(_):
        raise RuntimeError(f"private={private_path}; answer={trial.oracle_sha256}")

    with pytest.raises(RuntimeError, match="proposal infrastructure failed") as error:
        run_external_fixture_manifest_trial(
            tmp_path / "runs" / "state.sqlite", image="sha256:" + "a" * 64,
            platform=None, manifest=manifest, proposer=fail_proposal,
        )
    assert private_path not in str(error.value)
    assert trial.oracle_sha256 not in str(error.value)


def test_manifest_sanitizes_sandbox_configuration_failure(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    case, _ = _manifest_case(tmp_path, "case-1", 2)
    manifest = _write_trial_manifest(tmp_path, [case])
    secret = f"private={tmp_path}/oracle-sensitive-value"

    def fail_configure(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(workflow_model_trial, "configure", fail_configure)
    with pytest.raises(RuntimeError, match="sandbox configuration failed") as error:
        run_external_fixture_manifest_trial(
            tmp_path / "runs" / "state.sqlite", image="sha256:" + "a" * 64,
            platform=None, manifest=manifest,
            proposer=lambda _: pytest.fail("configuration failure reached proposer"),
        )
    assert secret not in str(error.value)


def test_manifest_counts_invalid_proposal_as_case_failure(tmp_path):
    tmp_path.chmod(0o700)
    case, _ = _manifest_case(tmp_path, "stable-case", 2)
    manifest = _write_trial_manifest(tmp_path, [case])
    result = run_external_fixture_manifest_trial(
        tmp_path / "runs" / "state.sqlite", image="sha256:" + "a" * 64,
        platform=None, manifest=manifest, proposer=lambda _: b"not-json",
    )
    assert result["cases"][0]["case_id"] == "stable-case"
    assert result["cases"][0]["failure"] == "invalid_proposal"
    assert result["summary"]["total"] == result["summary"]["failed"] == 1


def test_manifest_rejects_non_boolean_replay_status_as_infrastructure_failure(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    case, trial = _manifest_case(tmp_path, "case-1", 2)
    manifest = _write_trial_manifest(tmp_path, [case])
    monkeypatch.setattr(workflow_model_trial, "replay_workflow_in_sandbox",
                        lambda *args, **kwargs: {"ok": 1, "reproducible": True,
                                                 "oracle_match": True})
    with pytest.raises(RuntimeError, match="sandbox or run infrastructure failed"):
        run_external_fixture_manifest_trial(
            tmp_path / "runs" / "state.sqlite", image="sha256:" + "a" * 64,
            platform=None, manifest=manifest, proposer=lambda _: trial.workflow_json,
        )


@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS extended ACLs")
def test_manifest_rejects_acl_grant_on_private_manifest(tmp_path):
    tmp_path.chmod(0o700)
    case, _ = _manifest_case(tmp_path, "case-1", 2)
    manifest = _write_trial_manifest(tmp_path, [case])
    entry = "everyone allow read"
    subprocess.run(["/bin/chmod", "+a", entry, manifest], check=True, timeout=5)
    try:
        with pytest.raises(ValueError, match="must have no extended ACL grants"):
            run_external_fixture_manifest_trial(
                tmp_path / "runs" / "state.sqlite", image="sha256:" + "a" * 64,
                platform=None, manifest=manifest,
                proposer=lambda _: pytest.fail("manifest ACL grant reached proposer"),
            )
        assert not (tmp_path / "runs").exists()
    finally:
        subprocess.run(["/bin/chmod", "-a", entry, manifest], check=True, timeout=5)


def test_manifest_cli_emits_answer_free_json_and_returns_failure_status(monkeypatch, capsys):
    report = {"cases": [{"case_id": "case-1", "ok": False,
                         "reproducible": False, "oracle_match": False,
                         "selected_steps": [], "failure": "proposal_or_replay"}],
              "summary": {"total": 1, "passed": 0, "failed": 1, "pass_rate": 0.0}}
    monkeypatch.setattr(unseen_trial_cli, "run_external_fixture_manifest_trial",
                        lambda *args, **kwargs: report)
    monkeypatch.setattr(sys, "argv", ["issue7_unseen_trial.py", "--database", "state.sqlite",
                                      "--image", "sha256:" + "a" * 64,
                                      "--manifest", "private.json"])
    assert unseen_trial_cli.main() == 2
    assert json.loads(capsys.readouterr().out) == report


def test_manifest_cli_suppresses_private_setup_exception(monkeypatch, capsys, tmp_path):
    secret = f"{tmp_path}/private-oracle-flag-shaped-value"

    def fail_setup(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(unseen_trial_cli, "run_external_fixture_manifest_trial", fail_setup)
    monkeypatch.setattr(sys, "argv", ["issue7_unseen_trial.py", "--database", "state.sqlite",
                                      "--image", "sha256:" + "a" * 64,
                                      "--manifest", "private.json"])
    with pytest.raises(SystemExit) as error:
        unseen_trial_cli.main()
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert secret not in captured.err
    assert "details are suppressed" in captured.err
    assert captured.out == ""


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


@pytest.mark.skipif(not os.environ.get("METIS_TEST_SANDBOX_IMAGE"),
                    reason="requires an immutable METIS_TEST_SANDBOX_IMAGE")
def test_external_fixture_real_docker_replay_keeps_oracle_private(tmp_path, monkeypatch):
    # Prepare a benign input independently of METIS's built-in fixture generator.
    tmp_path.chmod(0o700)
    message = b"Workflow canary " + secrets.token_hex(24).encode()
    challenge = base64.b32encode(message.hex().encode("ascii"))
    fixture = tmp_path / "external-input.txt"
    fixture.write_bytes(challenge)
    private = tmp_path / "reviewer"
    private.mkdir(mode=0o700)
    openssl = shutil.which("openssl")
    assert openssl is not None
    expected_sha256 = subprocess.run([openssl, "dgst", "-sha256", "-binary"],
                                     input=message, capture_output=True, timeout=5,
                                     check=True).stdout.hex()
    oracle = private / "independent.sha256"
    oracle.write_text(expected_sha256 + "\n")
    oracle.chmod(0o600)

    plan = json.dumps({
        "schema_version": 1, "input_artifact": "challenge.txt",
        "steps": [{"tool": "base32_decode"}, {"tool": "hex_decode"}],
    }).encode()
    proposer = None
    if sys.platform == "darwin":
        # Drive the production Seatbelt proposal path with a harmless local stand-in.
        # It exits unsuccessfully unless the OS denies opening the oracle by its real path.
        canary_dir = tmp_path / "canary-package"
        canary_dir.mkdir()
        stand_in = canary_dir / "proposer.pl"
        stand_in.write_text(
            'use strict; use warnings; use Errno qw(EACCES EPERM);\n'
            'my ($flag, $output, $oracle, $token, $plan) = @ARGV;\n'
            'die "incorrect CLI flag" unless $flag eq "--ephemeral";\n'
            'my $prompt = do { local $/; <STDIN> };\n'
            'die "fixture missing" unless index($prompt, $token) >= 0;\n'
            'die "oracle opened" if open(my $secret, "<", $oracle);\n'
            'die "oracle lookup did not fail with permission denied" '
            'unless $! == EACCES || $! == EPERM;\n'
            'open(my $reply, ">", $output) or die "cannot write proposal";\n'
            'print {$reply} $plan;\n'
        )

        class CanaryCLI:
            executable = "/usr/bin/perl"
            hosts: tuple[str, ...] = ()

            def __init__(self, *, isolation):
                assert isolation == "required"

            def check(self):
                pass

            def argv(self, workdir, schema, output, model):
                return [self.executable, str(stand_in), str(output), str(oracle),
                        challenge.decode("ascii"), plan.decode("ascii")]

            def environment(self):
                return {}

            def protected_roots(self, temp_root):
                # Prove the oracle-specific rule even when defaults omit this path.
                return []

        monkeypatch.setattr(workflow_model_trial, "CodexCLI", CanaryCLI)
        monkeypatch.setattr(workflow_model_trial, "native_codex",
                            lambda executable: (executable, canary_dir))
        monkeypatch.setattr(workflow_model_trial, "default_codex_home",
                            lambda: tmp_path / "empty-codex-home")
        monkeypatch.setattr(workflow_model_trial, "upstream_proxy", lambda: None)
    else:
        def proposer(payload):
            assert payload == challenge
            return plan

    database = tmp_path / "run-workspace" / "state.sqlite"
    report = run_external_fixture_trial(
        database, image=os.environ["METIS_TEST_SANDBOX_IMAGE"],
        platform=os.environ.get("METIS_TEST_SANDBOX_PLATFORM"),
        fixture=fixture, oracle=oracle, proposer=proposer,
    )
    assert report["ok"] and report["reproducible"] and report["oracle_match"]
    assert set(report) == {"fixture", "run_id", "selected_steps", "reproducible",
                           "oracle_match", "ok", "fixture_sha256"}
    session = CodexSession(database)
    run_id = report["run_id"]
    events = session.store.export_jsonl(run_id)
    artifact_root = session.artifact_root(run_id)
    assert artifact_root is not None
    artifacts = list(artifact_root.iterdir())
    assert sorted(path.name for path in artifacts) == ["00-challenge.txt", "01-workflow.json"]
    visible = (json.dumps(report) + events).encode() + b"".join(path.read_bytes() for path in artifacts)
    for private_value in (message, expected_sha256.encode(), os.fsencode(oracle)):
        if private_value in visible:
            pytest.fail("private fixture data escaped into an output surface", pytrace=False)
