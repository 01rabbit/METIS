from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from metis.core.llama_server_backend import (
    LlamaBackendError,
    LlamaBackendRefused,
    LlamaBackendStopped,
    LlamaServerBackend,
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def backend_files(tmp_path):
    binary = tmp_path / "fake-server"
    binary.write_text('''#!/usr/bin/env python3
import json, socket, sys, os
from http.server import BaseHTTPRequestHandler
from socketserver import UnixStreamServer
args=sys.argv
sock=args[args.index('--host')+1]
model=args[args.index('--model')+1]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_GET(self):
  self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}')
 def do_POST(self):
  data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  if self.path=='/tokenize': out={'tokens':[1]*len(data['content'].split())}
  else:
   n=data['n_predict']; out={'content':'x'*n,'tokens_evaluated':len(data['prompt'].split()),'tokens_predicted':n,'model':model,'generation_settings':{'n_predict':n}}
  raw=json.dumps(out).encode(); self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers()
  if (self.path=='/completion' and data['prompt']=='slow trickle') or (self.path=='/tokenize' and data['content']=='slow tokenize'):
   for byte in raw:
    self.wfile.write(bytes([byte])); self.wfile.flush(); __import__('time').sleep(.05)
  else: self.wfile.write(raw)
UnixStreamServer(sock,Handler).serve_forever()
''')
    binary.chmod(0o700)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"synthetic model fixture")
    return {"binary": binary, "binary_sha256": _hash(binary), "model": model,
            "model_sha256": _hash(model), "database": tmp_path / "budget.sqlite",
            "budget_key": "test", "token_limit": 8, "max_output_tokens": 4}


def test_reservation_and_cap(backend_files):
    with LlamaServerBackend(**backend_files) as backend:
        assert backend.hard_cap_capable is False
        assert backend.complete("one two", n_predict=2, timeout_seconds=5) == ("xx", 2, 2)
        assert backend.complete("one", n_predict=2, timeout_seconds=5) == ("xx", 1, 2)
        with pytest.raises(LlamaBackendError):
            backend.complete("one", n_predict=1, timeout_seconds=5)
        socket_path = backend._socket
    assert not Path(socket_path).exists()
    with sqlite3.connect(backend_files["database"]) as db:
        assert db.execute("SELECT reserved FROM llama_token_budgets").fetchone() == (7,)


def test_admitted_completion_uses_claim_allowance_without_standalone_ledger(backend_files):
    backend_files["context_reservation"] = True
    with LlamaServerBackend(**backend_files) as backend:
        with pytest.raises(LlamaBackendError, match="cannot cover"):
            backend.complete_admitted("one", n_predict=2, token_cap=4097, timeout_seconds=5)
        assert backend.complete_admitted("one", n_predict=2, token_cap=4098,
                                         timeout_seconds=5) == ("xx", 1, 2)
    with sqlite3.connect(backend_files["database"]) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='llama_token_budgets'").fetchone() is None


def test_admitted_tokenization_deadline_remains_timeout(backend_files, monkeypatch):
    backend_files["context_reservation"] = True
    with LlamaServerBackend(**backend_files) as backend:
        def tokenization_timeout(route, *_args, **_kwargs):
            assert route == "/tokenize"
            raise LlamaBackendError("model call deadline exceeded")
        monkeypatch.setattr(backend, "_request_before", tokenization_timeout)
        with pytest.raises(LlamaBackendError, match="deadline"):
            backend.complete_admitted("one", n_predict=2, token_cap=4098, timeout_seconds=5)


def test_admitted_invalid_tokenization_response_is_precompletion_refusal(backend_files, monkeypatch):
    backend_files["context_reservation"] = True
    with LlamaServerBackend(**backend_files) as backend:
        def invalid_utf8(route, *_args, **_kwargs):
            assert route == "/tokenize"
            raise UnicodeDecodeError("utf8", b"\xff", 0, 1, "invalid response")
        monkeypatch.setattr(backend, "_request_before", invalid_utf8)
        with pytest.raises(LlamaBackendRefused, match="tokenization"):
            backend.complete_admitted("one", n_predict=2, token_cap=4098, timeout_seconds=5)


def test_pin_mismatch_refuses_launch(backend_files):
    backend_files["model_sha256"] = "0" * 64
    with pytest.raises(LlamaBackendError), LlamaServerBackend(**backend_files):
        pass


def test_server_start_has_no_warmup_or_inherited_llama_environment(backend_files, monkeypatch):
    from metis.core import llama_server_backend as module

    monkeypatch.setenv("LLAMA_ARG_DRAFT_MODEL", "/untrusted/draft.gguf")
    monkeypatch.setenv("LLAMA_ARG_WARMUP", "1")
    monkeypatch.setenv("LLAMA_ARG_CONTEXT_SHIFT", "1")
    monkeypatch.setenv("HTTP_PROXY", "http://untrusted.invalid")
    real_popen = module.subprocess.Popen
    seen = []

    def capture(*args, **kwargs):
        seen.append((args[0], kwargs["env"]))
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(module.subprocess, "Popen", capture)
    with LlamaServerBackend(**backend_files):
        pass
    argv, child_env = seen[0]
    assert "--no-warmup" in argv and "--no-context-shift" in argv
    assert not any(key.startswith("LLAMA_ARG_") for key in child_env)
    assert "HTTP_PROXY" not in child_env
    assert child_env["HOME"] != os.environ["HOME"]


def test_startup_failure_before_any_prompt_has_no_reservation(backend_files):
    backend_files["startup_seconds"] = .2
    backend_files["binary"].write_text("#!/bin/sh\nexit 1\n")
    backend_files["binary_sha256"] = _hash(backend_files["binary"])
    with pytest.raises(LlamaBackendError, match="startup"), LlamaServerBackend(**backend_files):
        pass
    assert not backend_files["database"].exists()


def test_shared_concurrent_reservation(backend_files):
    backend_files["token_limit"] = 6
    results = []
    def worker():
        with LlamaServerBackend(**backend_files) as backend:
            try:
                backend.complete("one two", n_predict=2, timeout_seconds=5)
                results.append("admitted")
            except LlamaBackendError:
                results.append("denied")
    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert sorted(results) == ["admitted", "denied"]


def test_completion_failure_charges_full_reservation_and_stops_process(backend_files, monkeypatch):
    with LlamaServerBackend(**backend_files) as backend:
        original = backend._request
        def fail_completion(route, payload, *, timeout):
            if route == "/completion":
                raise LlamaBackendError("synthetic timeout")
            return original(route, payload, timeout=timeout)
        monkeypatch.setattr(backend, "_request", fail_completion)
        with pytest.raises(LlamaBackendError):
            backend.complete("one two", n_predict=3, timeout_seconds=5)
        assert backend._process is None
    with sqlite3.connect(backend_files["database"]) as db:
        assert db.execute("SELECT reserved FROM llama_token_budgets").fetchone() == (5,)


def test_first_call_above_shared_limit_is_not_committed(backend_files):
    backend_files["token_limit"] = 2
    with LlamaServerBackend(**backend_files) as backend, pytest.raises(LlamaBackendError):
        backend.complete("one two", n_predict=1, timeout_seconds=5)
    with sqlite3.connect(backend_files["database"]) as db:
        table = db.execute("SELECT 1 FROM sqlite_master WHERE name=?",
                           ("llama_token_budgets",)).fetchone()
        assert table is None or db.execute("SELECT COUNT(*) FROM llama_token_budgets").fetchone() == (0,)


def test_usage_mismatch_stops_server_and_retains_charge(backend_files, monkeypatch):
    with LlamaServerBackend(**backend_files) as backend:
        original = backend._request
        def bad_usage(route, payload, *, timeout):
            result = original(route, payload, timeout=timeout)
            if route == "/completion":
                result["tokens_predicted"] = 99
            return result
        monkeypatch.setattr(backend, "_request", bad_usage)
        with pytest.raises(LlamaBackendError):
            backend.complete("one two", n_predict=2, timeout_seconds=5)
        assert backend._process is None
    with sqlite3.connect(backend_files["database"]) as db:
        assert db.execute("SELECT reserved FROM llama_token_budgets").fetchone() == (4,)


def test_tokenizer_completion_disagreement_is_detected_only_after_inference(backend_files, monkeypatch):
    """A post-call mismatch cannot establish a strict pre-call token ceiling."""
    backend_files["token_limit"] = 4
    completed = []
    with LlamaServerBackend(**backend_files) as backend:
        original = backend._request

        def disagree(route, payload, *, timeout):
            result = original(route, payload, timeout=timeout)
            if route == "/completion":
                completed.append(True)
                result["tokens_evaluated"] += 1
            return result

        monkeypatch.setattr(backend, "_request", disagree)
        with pytest.raises(LlamaBackendError, match="usage or settings mismatch"):
            backend.complete("one two", n_predict=2, timeout_seconds=5)
    assert completed == [True]
    with sqlite3.connect(backend_files["database"]) as db:
        assert db.execute("SELECT reserved FROM llama_token_budgets").fetchone() == (4,)
    assert LlamaServerBackend.hard_cap_capable is False


def test_full_context_reservation_covers_tokenizer_disagreement(backend_files, monkeypatch):
    backend_files.update(token_limit=4098, context_reservation=True)
    with LlamaServerBackend(**backend_files) as backend:
        original = backend._request

        def disagree(route, payload, *, timeout):
            result = original(route, payload, timeout=timeout)
            if route == "/completion":
                result["tokens_evaluated"] = 100
            return result

        monkeypatch.setattr(backend, "_request", disagree)
        content, evaluated, predicted = backend.complete("one two", n_predict=2,
                                                         timeout_seconds=5)
        assert (content, evaluated, predicted) == ("xx", 100, 2)
        with pytest.raises(LlamaBackendError, match="budget"):
            backend.complete("one", n_predict=1, timeout_seconds=5)
    with sqlite3.connect(backend_files["database"]) as db:
        assert db.execute("SELECT reserved FROM llama_token_budgets").fetchone() == (4098,)


def test_full_context_reservation_rejects_oversized_prompt_before_completion(backend_files, monkeypatch):
    backend_files.update(token_limit=5000, context_reservation=True)
    completed = []
    with LlamaServerBackend(**backend_files) as backend:
        original = backend._request

        def track_completion(route, payload, *, timeout):
            if route == "/completion":
                completed.append(True)
            return original(route, payload, timeout=timeout)

        monkeypatch.setattr(backend, "_request", track_completion)
        with pytest.raises(LlamaBackendError, match="exceeds reserved context"):
            backend.complete("one " * 4097, n_predict=2, timeout_seconds=5)
        assert completed == []
    with sqlite3.connect(backend_files["database"]) as db:
        table = db.execute("SELECT 1 FROM sqlite_master WHERE name=?",
                           ("llama_token_budgets",)).fetchone()
        assert table is None or db.execute("SELECT COUNT(*) FROM llama_token_budgets").fetchone() == (0,)


def test_full_context_reservation_is_shared_across_processes(backend_files):
    backend_files.update(token_limit=4098, context_reservation=True)
    results = []

    def worker():
        with LlamaServerBackend(**backend_files) as backend:
            try:
                backend.complete("one", n_predict=2, timeout_seconds=5)
                results.append("admitted")
            except LlamaBackendError:
                results.append("denied")

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["admitted", "denied"]


def test_reentry_refused_without_losing_original_process(backend_files):
    with LlamaServerBackend(**backend_files) as backend:
        original = backend._process
        with pytest.raises(LlamaBackendError):
            backend.__enter__()
        assert backend._process is original and original.poll() is None


def test_whole_call_deadline_stops_slow_trickle_and_keeps_charge(backend_files):
    with LlamaServerBackend(**backend_files) as backend:
        started = time.monotonic()
        with pytest.raises(LlamaBackendError, match="deadline"):
            backend.complete("slow trickle", n_predict=2, timeout_seconds=.25)
        elapsed = time.monotonic() - started
        assert elapsed < 2
        assert backend._process is None
    with sqlite3.connect(backend_files["database"]) as db:
        assert db.execute("SELECT reserved FROM llama_token_budgets").fetchone() == (4,)


def test_whole_call_deadline_during_tokenize_stops_without_charge(backend_files):
    with LlamaServerBackend(**backend_files) as backend:
        started = time.monotonic()
        with pytest.raises(LlamaBackendError, match="deadline"):
            backend.complete("slow tokenize", n_predict=2, timeout_seconds=.25)
        assert time.monotonic() - started < 2
        assert backend._process is None
    assert not backend_files["database"].exists()


def test_live_cancellation_stops_process_and_retains_reservation(backend_files):
    event = threading.Event()
    def cancel_soon():
        time.sleep(.15)
        event.set()
    with LlamaServerBackend(**backend_files) as backend:
        trigger = threading.Thread(target=cancel_soon)
        trigger.start()
        with pytest.raises(LlamaBackendStopped, match="cancelled"):
            backend.complete("slow trickle", n_predict=2, timeout_seconds=5,
                             should_stop=event.is_set)
        trigger.join()
        assert backend._process is None
    with sqlite3.connect(backend_files["database"]) as db:
        assert db.execute("SELECT reserved FROM llama_token_budgets").fetchone() == (4,)
