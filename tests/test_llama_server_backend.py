from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path

import pytest

from metis.core.llama_server_backend import LlamaBackendError, LlamaServerBackend


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
  raw=json.dumps(out).encode(); self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
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


def test_pin_mismatch_refuses_launch(backend_files):
    backend_files["model_sha256"] = "0" * 64
    with pytest.raises(LlamaBackendError), LlamaServerBackend(**backend_files):
        pass


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


def test_reentry_refused_without_losing_original_process(backend_files):
    with LlamaServerBackend(**backend_files) as backend:
        original = backend._process
        with pytest.raises(LlamaBackendError):
            backend.__enter__()
        assert backend._process is original and original.poll() is None
