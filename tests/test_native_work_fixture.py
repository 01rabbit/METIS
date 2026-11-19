import asyncio
import errno
import hashlib
import json
import os
import platform
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier

import pytest

from metis.core.study_token_admission import (
    FixtureClaimBusy,
    SlotTokenPin,
    StudyTokenAdmission,
    StudyTokenPin,
    TokenAttempt,
)
from metis.evaluation import native_build_identity as identity
from metis.evaluation import native_work_fixture as fixture

# The fixture-only controller uses this staged binary as a bounded stand-in for
# the native receipt protocol. The real GGUF is verified in a separate smoke.
_FAKE_SERVER = """
import http.server
import json
import os
import pathlib
import signal
import socket
import socketserver
import stat
import sys
import time

flags = dict(zip(sys.argv[1::2], sys.argv[2::2]))
mode = MODENAME
limit = PROFILE_LIMIT
end = PROFILE_END
expected_cap = EXPECTED_CAP
cap = int(flags["--metis-work-budget"])
nonce = flags["--metis-launch-nonce"]
fd = int(flags["--metis-receipt-fd"])
socket_path = pathlib.Path(flags["--socket"])
model = pathlib.Path(flags["--model"])
assert cap == expected_cap
assert stat.S_IMODE(model.stat().st_mode) == 0o400
assert stat.S_IMODE(pathlib.Path(sys.argv[0]).stat().st_mode) == 0o500
assert stat.S_IMODE(socket_path.parent.stat().st_mode) == 0o700

if mode == "crash":
    os._exit(75)
if mode == "timeout":
    time.sleep(20)
    os._exit(0)
if mode == "startup_retry":
    value = dict(version=1, nonce=nonce, cap=cap, charged=1, reason="cap_denied")
    os.write(fd, json.dumps(value).encode() + bytes([10]))
    os._exit(75)

def finish(*_):
    if mode != "missing":
        value = dict(version=1, nonce=nonce, cap=cap, charged=21 + (limit if end == "limit" else 1), reason="shutdown")
        if mode == "wrong_nonce":
            value["nonce"] = "0" * 32 if nonce != "0" * 32 else "1" * 32
        if mode == "wrong_cap":
            value["cap"] = cap + 1
        if mode == "over_cap":
            value["charged"] = cap + 1
        if mode == "under_work":
            value["charged"] = 0
        if mode == "extra_field":
            value["extra"] = True
        raw = (json.dumps(value) + "\\n").encode()
        if mode == "duplicate":
            raw += raw
        if mode == "duplicate_key":
            raw = raw.replace(b'"version": 1,', b'"version": 1, "version": 1,')
        os.write(fd, raw)
    os._exit(74 if mode == "wrong_status" else 0)

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls = 0

    def log_message(self, *_):
        pass

    def send_json(self, result):
        raw = json.dumps(result).encode()
        if mode == "duplicate_http_counter" and "tokens_predicted" in result:
            raw = raw.replace(b'"tokens_predicted": 1,', b'"tokens_predicted": 2, "tokens_predicted": 1,')
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        assert self.path == "/health"
        self.send_json({"status": "ok"})

    def do_POST(self):
        content = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/tokenize":
            assert content == {"content": "One day, a rabbit ran down the road.", "add_special": True}
            tokens = [1, 385, 328, 432, 261, 352, 412, 430, 430, 275, 352, 303, 279, 327, 416, 265, 352, 414, 380, 426]
            if mode == "bad_prompt_count":
                tokens.pop()
            if mode == "bad_prompt_id":
                tokens[-1] = 1
            self.send_json({"tokens": tokens})
            return
        assert self.path == "/completion"
        assert mode not in ("bad_prompt_count", "bad_prompt_id")
        Handler.calls += 1
        assert Handler.calls == 1
        stop = [" He"] if end == "word" else []
        bias = [[2, 100]] if end == "eos" else []
        assert content == {
            "prompt": "One day, a rabbit ran down the road.",
            "n_predict": limit, "temperature": 0, "cache_prompt": False,
            "stream": False, "ignore_eos": False, "stop": stop, "logit_bias": bias,
        }
        if mode == "trickle":
            self.send_response(200)
            self.send_header("Content-Length", "500")
            self.end_headers()
            self.wfile.write(b"{")
            self.wfile.flush()
            time.sleep(20)
        self.send_json({
            "tokens_evaluated": 21 if mode == "bad_evaluated" else 20,
            "tokens_predicted": limit + 1 if mode == "bad_generated" else (limit if end == "limit" else 1),
            "content": " text" if end == "limit" else "",
            "stop_type": end, "stopping_word": stop[0] if stop else "", "truncated": False,
            "generation_settings": {
                "n_predict": limit + 1 if mode == "bad_settings" else limit,
                "max_tokens": limit, "speculative.types": "draft" if mode == "draft_settings" else "none,none",
                "backend_sampling": False, "stream": False, "ignore_eos": False, "temperature": 0,
                "stop": stop, "logit_bias": [{"token": 2, "bias": 100}] if end == "eos" else [],
            },
        })


signal.signal(signal.SIGTERM, signal.SIG_IGN if mode == "ignore_shutdown" else finish)
with socketserver.UnixStreamServer(str(socket_path), Handler) as server:
    server.serve_forever()
"""


def _setup(tmp_path, monkeypatch, mode, *, n_predict=1, end="limit", cap=30):
    binary = tmp_path / "server"
    script = (_FAKE_SERVER.replace("MODENAME", repr(mode)).replace("PROFILE_LIMIT", str(n_predict))
              .replace("PROFILE_END", repr(end)).replace("EXPECTED_CAP", str(cap - n_predict)))
    binary.write_text(f"#!{sys.executable}\n" + script)
    model = tmp_path / "fixture.gguf"
    model.write_bytes(b"fixture test bytes")
    model_digest = hashlib.sha256(model.read_bytes()).hexdigest()
    monkeypatch.setattr(fixture, "FIXTURE_MODEL_SHA256", model_digest)
    monkeypatch.setattr(identity, "_PUBLIC_MODEL_SHA256", model_digest)
    patch = tmp_path / "approved.patch"
    patch.write_bytes(b"synthetic patch")
    manifest = tmp_path / "native-build.json"
    binary_digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    manifest.write_text(json.dumps({
        "version": 1, "profile": identity._PROFILE, "source_commit": identity._SOURCE_COMMIT,
        "target_os": platform.system(), "target_arch": platform.machine(),
        "compiler_id": "fixture", "compiler_version": "1", "cmake_version": "1",
        "binary_sha256": binary_digest, "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
    }))
    approval = {
        "manifest": manifest, "patch": patch,
        "expected_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    }
    study = StudyTokenPin(
        study_id="fixture", protocol_sha256=fixture.fixture_protocol_sha256(n_predict, end=end),
        runtime_sha256=binary_digest,
        model_sha256=model_digest, token_limit=cap,
        native_manifest_sha256=approval["expected_manifest_sha256"],
    )
    slot = SlotTokenPin(run_id="run", task_id="fixture", repetition=0, arm="test", token_limit=cap)
    attempt = TokenAttempt(assignment_id="assignment", attempt_id="attempt", turn_reservation_id=1,
                           prompt_sha256=fixture.FIXTURE_PROMPT_SHA256, tokens=cap)
    admission = StudyTokenAdmission(tmp_path / "ledger.sqlite")
    return admission, admission.reserve(study, slot, attempt), binary, model, approval


@pytest.mark.parametrize(("mode", "status", "exit_status", "work"), [
    ("valid", "completed", 0, 22),
    ("missing", "receipt_invalid", 0, None),
    ("ignore_shutdown", "receipt_invalid", -9, None),
    ("wrong_nonce", "receipt_invalid", 0, None),
    ("wrong_cap", "receipt_invalid", 0, None),
    ("over_cap", "receipt_invalid", 0, None),
    ("under_work", "receipt_invalid", 0, None),
    ("bad_prompt_count", "receipt_invalid", -9, None),
    ("bad_prompt_id", "receipt_invalid", -9, None),
    ("bad_evaluated", "receipt_invalid", -9, None),
    ("bad_generated", "receipt_invalid", -9, None),
    ("duplicate_http_counter", "receipt_invalid", -9, None),
    ("bad_settings", "receipt_invalid", -9, None),
    ("draft_settings", "receipt_invalid", -9, None),
    ("duplicate", "receipt_invalid", 0, None),
    ("duplicate_key", "receipt_invalid", 0, None),
    ("extra_field", "receipt_invalid", 0, None),
    ("wrong_status", "receipt_invalid", 74, None),
    ("crash", "receipt_invalid", 75, None),
    ("timeout", "timeout", -9, None),
    ("trickle", "timeout", -9, None),
])
def test_private_launch_verifies_terminal_receipt_and_keeps_full_charge(tmp_path, monkeypatch, mode,
                                                                      status, exit_status, work):
    admission, receipt, binary, model, approval = _setup(tmp_path, monkeypatch, mode)
    outcome = fixture.qualify_native_launch(
        admission, receipt, binary=binary, model=model, **approval, seconds=0.7 if mode in ("timeout", "trickle") else 4,
    )
    assert (outcome.status, outcome.exit_status, outcome.observed_work) == (status, exit_status, work)
    with closing(sqlite3.connect(admission.database)) as db:
        assert db.execute(
            "SELECT status, exit_status, observed_work, native_manifest_sha256 FROM study_token_outcomes"
        ).fetchall() == [
            (status, exit_status, work, approval["expected_manifest_sha256"]),
        ]
    extra_attempt = receipt.attempt.model_copy(update={"turn_reservation_id": 2, "tokens": 1})
    with pytest.raises(ValueError, match="study token budget exhausted"):
        admission.reserve(receipt.study, receipt.slot, extra_attempt)
    with pytest.raises(ValueError, match="already claimed"):
        fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval)


@pytest.mark.parametrize("kind", ["binary", "model", "symlink", "prompt", "unknown_model", "forged_attempt"])
def test_unverified_launch_does_not_reach_popen(tmp_path, monkeypatch, kind):
    admission, receipt, binary, model, approval = _setup(tmp_path, monkeypatch, "valid")
    if kind == "binary":
        binary.write_bytes(b"substituted binary")
    elif kind == "model":
        model.write_bytes(b"GGUF split.count altered")
    elif kind == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(model)
        model = alias
    elif kind == "prompt":
        receipt = receipt.model_copy(update={"attempt": receipt.attempt.model_copy(
            update={"prompt_sha256": "a" * 64},
        )})
    elif kind == "unknown_model":
        receipt = receipt.model_copy(update={"study": receipt.study.model_copy(
            update={"model_sha256": "a" * 64},
        )})
    else:
        receipt = receipt.model_copy(update={"attempt": receipt.attempt.model_copy(update={"tokens": 29})})

    def unexpected(*args, **kwargs):
        pytest.fail("unverified launch reached Popen")

    monkeypatch.setattr(fixture.subprocess, "Popen", unexpected)
    if kind == "symlink":
        with pytest.raises(OSError) as error:
            fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval)
        assert error.value.errno == errno.ELOOP
    else:
        with pytest.raises(ValueError):
            fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval)
    with closing(sqlite3.connect(admission.database)) as db:
        assert db.execute("SELECT count(*) FROM study_token_launches").fetchone() == (0,)


def test_one_process_can_launch_for_racing_controllers(tmp_path, monkeypatch):
    admission, receipt, binary, model, approval = _setup(tmp_path, monkeypatch, "valid")
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=5)
        try:
            return fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval).status
        except ValueError as error:
            assert isinstance(error, FixtureClaimBusy) or "already claimed" in str(error)
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(run) for _ in range(2)]
        assert sorted(result.result(timeout=10) for result in results) == ["completed", "denied"]


def test_cancelled_fixture_preserves_reaped_worker_status(tmp_path, monkeypatch):
    admission, receipt, binary, model, approval = _setup(tmp_path, monkeypatch, "trickle")

    async def cancel_after_readiness(path, process, seconds, request):
        async with asyncio.timeout(seconds):
            while not path.exists():
                await asyncio.sleep(0.01)
        raise KeyboardInterrupt

    monkeypatch.setattr(fixture, "_complete_once", cancel_after_readiness)
    outcome = fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval)
    assert (outcome.status, outcome.exit_status, outcome.observed_work) == ("cancelled", -9, None)
    with closing(sqlite3.connect(admission.database)) as db:
        assert db.execute("SELECT status, exit_status FROM study_token_outcomes").fetchall() == [("cancelled", -9)]
    with pytest.raises(ValueError, match="already claimed"):
        fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval)


def test_failed_spawn_keeps_claim_and_records_terminal_failure(tmp_path, monkeypatch):
    admission, receipt, binary, model, approval = _setup(tmp_path, monkeypatch, "valid")

    def fail(*args, **kwargs):
        raise OSError(errno.EACCES, "synthetic launch failure")

    monkeypatch.setattr(fixture.subprocess, "Popen", fail)
    outcome = fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval)
    assert outcome.status == "launch_failed"
    with pytest.raises(ValueError, match="already claimed"):
        fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval)

def test_public_native_fixture_cap_matrix(tmp_path):
    binary_file = os.environ.get("METIS_NATIVE_FIXTURE_BINARY")
    model_file = os.environ.get("METIS_NATIVE_FIXTURE_MODEL")
    manifest_file = os.environ.get("METIS_NATIVE_FIXTURE_MANIFEST")
    patch_file = os.environ.get("METIS_NATIVE_FIXTURE_PATCH")
    expected = os.environ.get("METIS_NATIVE_FIXTURE_MANIFEST_SHA256")
    if not (binary_file and model_file and manifest_file and patch_file and expected):
        pytest.skip("requires the approved standalone build and public stories260K fixture")
    approval = {"manifest": Path(manifest_file), "patch": Path(patch_file), "expected_manifest_sha256": expected}

    binary, model = Path(binary_file), Path(model_file)
    with binary.open("rb") as artifact:
        runtime_sha256 = hashlib.file_digest(artifact, "sha256").hexdigest()
    for turn, (limit, end, cap, status, work) in enumerate([
        (1, "limit", 2, "cap_denied", 0),
        (1, "limit", 22, "cap_denied", 2),
        (1, "limit", 23, "completed", 22),
        (3, "limit", 26, "cap_denied", 23),
        (3, "limit", 27, "completed", 24),
        (3, "word", 24, "cap_denied", 2),
        (3, "word", 25, "completed", 22),
        (3, "eos", 24, "cap_denied", 2),
        (3, "eos", 25, "completed", 22),
    ], 1):
        # Each profile is independently committed. Use a separate ledger for
        # each cap boundary to keep the test cases independent.
        admission = StudyTokenAdmission(tmp_path / f"case-{turn}.sqlite")
        study = StudyTokenPin(
            study_id="native_fixture", protocol_sha256=fixture.fixture_protocol_sha256(limit, end=end),
            runtime_sha256=runtime_sha256, model_sha256=fixture.FIXTURE_MODEL_SHA256, token_limit=cap,
            native_manifest_sha256=expected,
        )
        slot = SlotTokenPin(run_id="public_fixture", task_id="native_fixture", repetition=0,
                            arm="test", token_limit=cap)
        attempt = TokenAttempt(assignment_id="fixture", attempt_id="attempt", turn_reservation_id=1,
                               prompt_sha256=fixture.FIXTURE_PROMPT_SHA256, tokens=cap)
        receipt = admission.reserve(study, slot, attempt)
        result = fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval,
                                               n_predict=limit, end=end)
        assert (result.status, result.observed_work) == (status, work)
        with closing(sqlite3.connect(admission.database)) as db:
            assert db.execute("SELECT SUM(tokens) FROM study_token_attempts").fetchone() == (cap,)

@pytest.mark.parametrize(("end", "work"), [("limit", 24), ("word", 22), ("eos", 22)])
def test_three_token_profile_reserves_full_output_headroom(tmp_path, monkeypatch, end, work):
    admission, receipt, binary, model, approval = _setup(tmp_path, monkeypatch, "valid", n_predict=3, end=end)
    outcome = fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval,
                                           n_predict=3, end=end)
    assert (outcome.status, outcome.observed_work) == ("completed", work)


def test_budget_and_profile_mismatches_do_not_claim_or_spawn(tmp_path, monkeypatch):
    admission, receipt, binary, model, approval = _setup(tmp_path, monkeypatch, "valid", n_predict=3, cap=3)

    def unexpected(*args, **kwargs):
        pytest.fail("unverified output policy reached Popen")

    monkeypatch.setattr(fixture.subprocess, "Popen", unexpected)
    for limit, end, message in [(1, "limit", "sampling profile"), (3, "word", "sampling profile"),
                                (3, "limit", "no positive native cap")]:
        with pytest.raises(ValueError, match=message):
            fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval,
                                          n_predict=limit, end=end)
    with closing(sqlite3.connect(admission.database)) as db:
        assert db.execute("SELECT count(*) FROM study_token_launches").fetchone() == (0,)


def test_startup_retry_denial_keeps_admission_charged(tmp_path, monkeypatch):
    admission, receipt, binary, model, approval = _setup(tmp_path, monkeypatch, "startup_retry", cap=2)
    outcome = fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval)
    assert (outcome.status, outcome.exit_status, outcome.observed_work) == ("cap_denied", 75, 1)
    with pytest.raises(ValueError, match="already claimed"):
        fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval)


@pytest.mark.parametrize("kind", [
    "foreign_manifest", "changed_patch", "wrong_target", "runtime_pin", "forged_provenance", "missing_pin",
])
def test_unapproved_build_stops_before_staging_or_launch(tmp_path, monkeypatch, kind):
    admission, receipt, binary, model, approval = _setup(tmp_path, monkeypatch, "valid")
    if kind == "foreign_manifest":
        binary.write_bytes(b"different binary")
        manifest = json.loads(approval["manifest"].read_bytes())
        manifest["binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
        approval["manifest"].write_text(json.dumps(manifest))
    elif kind == "changed_patch":
        approval["patch"].write_bytes(b"different patch")
    elif kind == "wrong_target":
        path = approval["manifest"]
        manifest = json.loads(path.read_bytes())
        target = ("Linux", "x86_64") if platform.system() == "Darwin" else ("Darwin", "arm64")
        manifest["target_os"], manifest["target_arch"] = target
        path.write_text(json.dumps(manifest))
        approval["expected_manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        changed = receipt.study.model_copy(update={"native_manifest_sha256": approval["expected_manifest_sha256"]})
        receipt = receipt.model_copy(update={"study": changed})
    elif kind == "forged_provenance":
        _make_foreign_provenance(approval)
    else:
        changed = receipt.study.model_copy(update=(
            {"runtime_sha256": "f" * 64} if kind == "runtime_pin" else {"native_manifest_sha256": None}
        ))
        receipt = receipt.model_copy(update={"study": changed})

    def unexpected(*args, **kwargs):
        pytest.fail("unapproved build crossed preflight")

    monkeypatch.setattr(fixture, "_stage", unexpected)
    monkeypatch.setattr(fixture.subprocess, "Popen", unexpected)
    with pytest.raises(ValueError):
        fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval)
    with closing(sqlite3.connect(admission.database)) as db:
        assert db.execute("SELECT count(*) FROM study_token_launches").fetchone() == (0,)


@pytest.mark.parametrize("replaced_executable", [False, True])
def test_substituted_staged_bytes_do_not_reach_process_launch(tmp_path, monkeypatch, replaced_executable):
    admission, receipt, binary, model, approval = _setup(tmp_path, monkeypatch, "valid")
    stage = fixture._stage

    def substitute(source, destination, expected, *, limit, executable=False):
        stage(source, destination, expected, limit=limit, executable=executable)
        if executable == replaced_executable:
            destination.chmod(0o600)
            destination.write_bytes(b"substituted after staging")

    def unexpected(*args, **kwargs):
        pytest.fail("substituted artifact reached Popen")

    monkeypatch.setattr(fixture, "_stage", substitute)
    monkeypatch.setattr(fixture.subprocess, "Popen", unexpected)
    with pytest.raises(ValueError, match="native binary digest mismatch|registered single-file"):
        fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval)
    with closing(sqlite3.connect(admission.database)) as db:
        assert db.execute("SELECT count(*) FROM study_token_launches").fetchone() == (0,)


def test_controller_uses_approved_copies_after_original_paths_change(tmp_path, monkeypatch):
    admission, receipt, binary, model, approval = _setup(tmp_path, monkeypatch, "valid")
    stage = fixture._stage

    def replace_original(source, destination, expected, *, limit, executable=False):
        stage(source, destination, expected, limit=limit, executable=executable)
        source.write_bytes(b"source replaced after approved copy")

    monkeypatch.setattr(fixture, "_stage", replace_original)
    outcome = fixture.qualify_native_launch(admission, receipt, binary=binary, model=model, **approval)
    assert outcome.status == "completed"


def _make_foreign_provenance(approval):
    manifest_path, patch_path = approval["manifest"], approval["patch"]
    patch_path.write_bytes(b"different but internally consistent patch")
    document = json.loads(manifest_path.read_bytes())
    document["patch_sha256"] = hashlib.sha256(patch_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(document))
    approval["expected_manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def test_mutated_receipt_cannot_self_approve_foreign_provenance(tmp_path, monkeypatch):
    admission, receipt, binary, model, approval = _setup(tmp_path, monkeypatch, "valid")
    _make_foreign_provenance(approval)
    changed = receipt.study.model_copy(update={"native_manifest_sha256": approval["expected_manifest_sha256"]})
    forged_receipt = receipt.model_copy(update={"study": changed})

    def unexpected(*args, **kwargs):
        pytest.fail("forged receipt reached Popen")

    monkeypatch.setattr(fixture.subprocess, "Popen", unexpected)
    with pytest.raises(ValueError, match="committed reservation"):
        fixture.qualify_native_launch(admission, forged_receipt, binary=binary, model=model, **approval)
    with closing(sqlite3.connect(admission.database)) as db:
        assert db.execute("SELECT count(*) FROM study_token_launches").fetchone() == (0,)
