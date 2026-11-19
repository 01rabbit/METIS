import errno
import hashlib
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier

import pytest

from metis.core.study_token_admission import (
    SlotTokenPin,
    StudyTokenAdmission,
    StudyTokenPin,
    TokenAttempt,
)
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
cap = int(flags["--metis-work-budget"])
nonce = flags["--metis-launch-nonce"]
fd = int(flags["--metis-receipt-fd"])
socket_path = pathlib.Path(flags["--socket"])
model = pathlib.Path(flags["--model"])
assert stat.S_IMODE(model.stat().st_mode) == 0o400
assert stat.S_IMODE(pathlib.Path(sys.argv[0]).stat().st_mode) == 0o500
assert stat.S_IMODE(socket_path.parent.stat().st_mode) == 0o700

if mode == "crash":
    os._exit(75)
if mode == "timeout":
    time.sleep(20)
    os._exit(0)

def finish(*_):
    if mode != "missing":
        value = dict(version=1, nonce=nonce, cap=cap, charged=22, reason="shutdown")
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
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        assert self.path == "/health"
        self.send_json({"status": "ok"})

    def do_POST(self):
        assert self.path == "/completion"
        Handler.calls += 1
        assert Handler.calls == 1
        content = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert content == {
            "prompt": "One day, a rabbit ran down the road.",
            "n_predict": 1, "temperature": 0, "cache_prompt": False,
        }
        if mode == "trickle":
            self.send_response(200)
            self.send_header("Content-Length", "500")
            self.end_headers()
            self.wfile.write(b"{")
            self.wfile.flush()
            time.sleep(20)
        self.send_json({"tokens_evaluated": 20, "tokens_predicted": 1, "content": " text"})

signal.signal(signal.SIGTERM, signal.SIG_IGN if mode == "ignore_shutdown" else finish)
with socketserver.UnixStreamServer(str(socket_path), Handler) as server:
    server.serve_forever()
"""


def _setup(tmp_path, monkeypatch, mode):
    binary = tmp_path / "server"
    binary.write_text(f"#!{sys.executable}\n" + _FAKE_SERVER.replace("MODENAME", repr(mode)))
    model = tmp_path / "fixture.gguf"
    model.write_bytes(b"fixture test bytes")
    model_digest = hashlib.sha256(model.read_bytes()).hexdigest()
    monkeypatch.setattr(fixture, "FIXTURE_MODEL_SHA256", model_digest)
    study = StudyTokenPin(
        study_id="fixture", protocol_sha256="e" * 64,
        runtime_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        model_sha256=model_digest, token_limit=30,
    )
    slot = SlotTokenPin(run_id="run", task_id="fixture", repetition=0, arm="test", token_limit=30)
    attempt = TokenAttempt(assignment_id="assignment", attempt_id="attempt", turn_reservation_id=1,
                           prompt_sha256=fixture.FIXTURE_PROMPT_SHA256, tokens=30)
    admission = StudyTokenAdmission(tmp_path / "ledger.sqlite")
    return admission, admission.reserve(study, slot, attempt), binary, model


@pytest.mark.parametrize(("mode", "status", "exit_status", "work"), [
    ("valid", "completed", 0, 22),
    ("missing", "receipt_invalid", 0, None),
    ("ignore_shutdown", "receipt_invalid", -9, None),
    ("wrong_nonce", "receipt_invalid", 0, None),
    ("wrong_cap", "receipt_invalid", 0, None),
    ("over_cap", "receipt_invalid", 0, None),
    ("under_work", "receipt_invalid", 0, None),
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
    admission, receipt, binary, model = _setup(tmp_path, monkeypatch, mode)
    outcome = fixture.qualify_native_launch(
        admission, receipt, binary=binary, model=model, seconds=0.7 if mode in ("timeout", "trickle") else 4,
    )
    assert (outcome.status, outcome.exit_status, outcome.observed_work) == (status, exit_status, work)
    with closing(sqlite3.connect(admission.database)) as db:
        assert db.execute("SELECT status, exit_status, observed_work FROM study_token_outcomes").fetchall() == [
            (status, exit_status, work),
        ]
    extra_attempt = receipt.attempt.model_copy(update={"turn_reservation_id": 2, "tokens": 1})
    with pytest.raises(ValueError, match="study token budget exhausted"):
        admission.reserve(receipt.study, receipt.slot, extra_attempt)
    with pytest.raises(ValueError, match="already claimed"):
        fixture.qualify_native_launch(admission, receipt, binary=binary, model=model)


@pytest.mark.parametrize("kind", ["binary", "model", "symlink", "prompt", "unknown_model", "forged_attempt"])
def test_unverified_launch_does_not_reach_popen(tmp_path, monkeypatch, kind):
    admission, receipt, binary, model = _setup(tmp_path, monkeypatch, "valid")
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
            fixture.qualify_native_launch(admission, receipt, binary=binary, model=model)
        assert error.value.errno == errno.ELOOP
    else:
        with pytest.raises(ValueError):
            fixture.qualify_native_launch(admission, receipt, binary=binary, model=model)
    with closing(sqlite3.connect(admission.database)) as db:
        assert db.execute("SELECT count(*) FROM study_token_launches").fetchone() == (0,)


def test_one_process_can_launch_for_racing_controllers(tmp_path, monkeypatch):
    admission, receipt, binary, model = _setup(tmp_path, monkeypatch, "valid")
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=5)
        try:
            return fixture.qualify_native_launch(admission, receipt, binary=binary, model=model).status
        except ValueError as error:
            assert "already claimed" in str(error)
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(run) for _ in range(2)]
        assert sorted(result.result(timeout=10) for result in results) == ["completed", "denied"]


def test_failed_spawn_keeps_claim_and_records_terminal_failure(tmp_path, monkeypatch):
    admission, receipt, binary, model = _setup(tmp_path, monkeypatch, "valid")

    def fail(*args, **kwargs):
        raise OSError(errno.EACCES, "synthetic launch failure")

    monkeypatch.setattr(fixture.subprocess, "Popen", fail)
    outcome = fixture.qualify_native_launch(admission, receipt, binary=binary, model=model)
    assert outcome.status == "launch_failed"
    with pytest.raises(ValueError, match="already claimed"):
        fixture.qualify_native_launch(admission, receipt, binary=binary, model=model)

def test_public_native_fixture_cap_matrix(tmp_path):
    binary_file = os.environ.get("METIS_NATIVE_FIXTURE_BINARY")
    model_file = os.environ.get("METIS_NATIVE_FIXTURE_MODEL")
    if not binary_file or not model_file:
        pytest.skip("requires the pinned standalone build and public stories260K fixture")

    binary, model = Path(binary_file), Path(model_file)
    with binary.open("rb") as artifact:
        runtime_sha256 = hashlib.file_digest(artifact, "sha256").hexdigest()
    admission = StudyTokenAdmission(tmp_path / "ledger.sqlite")
    study = StudyTokenPin(study_id="native_fixture", protocol_sha256="f" * 64,
                          runtime_sha256=runtime_sha256, model_sha256=fixture.FIXTURE_MODEL_SHA256,
                          token_limit=44)
    slot = SlotTokenPin(run_id="public_fixture", task_id="native_fixture", repetition=0, arm="test", token_limit=44)
    for turn, (cap, status, work) in enumerate([
        (1, "cap_denied", 0),
        (21, "cap_denied", 2),
        (22, "completed", 22),
    ], 1):
        attempt = TokenAttempt(assignment_id="fixture", attempt_id=f"attempt{turn}", turn_reservation_id=turn,
                               prompt_sha256=fixture.FIXTURE_PROMPT_SHA256, tokens=cap)
        receipt = admission.reserve(study, slot, attempt)
        result = fixture.qualify_native_launch(admission, receipt, binary=binary, model=model)
        assert (result.status, result.observed_work) == (status, work)

    with closing(sqlite3.connect(admission.database)) as db:
        assert db.execute("SELECT SUM(tokens) FROM study_token_attempts").fetchone() == (44,)
