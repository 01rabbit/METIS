from __future__ import annotations

import hashlib
import os
import signal
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
    _sha256,
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


def test_startup_obeys_absolute_assignment_deadline(backend_files, monkeypatch):
    from metis.core import llama_server_backend as module

    backend_files["binary"].write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(1)\n")
    backend_files["binary"].chmod(0o700)
    backend_files["binary_sha256"] = _hash(backend_files["binary"])
    real_popen = module.subprocess.Popen
    real_tempdir = module.tempfile.TemporaryDirectory
    processes = []
    tempdirs = []

    def track_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    def track_tempdir(*args, **kwargs):
        tempdir = real_tempdir(*args, **kwargs)
        tempdirs.append(tempdir)
        return tempdir

    monkeypatch.setattr(module.subprocess, "Popen", track_popen)
    monkeypatch.setattr(module.tempfile, "TemporaryDirectory", track_tempdir)
    deadline = time.monotonic() + .5
    with pytest.raises(LlamaBackendError, match="startup deadline"), LlamaServerBackend(
        **backend_files, startup_seconds=10, deadline_monotonic=deadline,
    ):
        pytest.fail("server must not finish startup after the assignment deadline")
    assert time.monotonic() >= deadline
    assert processes and processes[0].poll() is not None
    assert processes[0].returncode == -signal.SIGTERM
    assert tempdirs and not Path(tempdirs[0].name).exists()


def test_pinned_artifact_hash_checks_cancellation_between_chunks(tmp_path):
    artifact = tmp_path / "large-model.gguf"
    artifact.write_bytes(b"x" * (4 * 1024 * 1024))
    checks = 0

    def cancel_during_hash():
        nonlocal checks
        checks += 1
        if checks == 4:
            raise LlamaBackendStopped("server startup cancelled")

    with pytest.raises(LlamaBackendStopped, match="cancelled"):
        _sha256(artifact, check=cancel_during_hash)
    assert checks == 4


def test_startup_hashing_honors_cancel_before_creating_process_or_tempdir(backend_files, monkeypatch):
    from metis.core import llama_server_backend as module

    backend_files["model"].write_bytes(b"x" * (4 * 1024 * 1024))
    backend_files["model_sha256"] = _hash(backend_files["model"])
    real_popen = module.subprocess.Popen
    real_tempdir = module.tempfile.TemporaryDirectory
    popen_calls = []
    tempdir_calls = []

    def track_popen(*args, **kwargs):
        popen_calls.append(args)
        return real_popen(*args, **kwargs)

    def track_tempdir(*args, **kwargs):
        tempdir_calls.append(args)
        return real_tempdir(*args, **kwargs)

    monkeypatch.setattr(module.subprocess, "Popen", track_popen)
    monkeypatch.setattr(module.tempfile, "TemporaryDirectory", track_tempdir)
    checks = 0

    def stop_after_two_model_chunks():
        nonlocal checks
        checks += 1
        return checks >= 7

    backend = LlamaServerBackend(**backend_files, should_stop=stop_after_two_model_chunks)
    with pytest.raises(LlamaBackendStopped, match="cancelled"):
        backend.__enter__()
    assert checks == 7
    assert popen_calls == []
    assert tempdir_calls == []


def test_cancelled_startup_kills_server_and_cleans_private_directory(backend_files, monkeypatch):
    from metis.core import llama_server_backend as module

    backend_files["binary"].write_text('''#!/usr/bin/env python3
import socket, sys, time
from http.server import BaseHTTPRequestHandler
from socketserver import UnixStreamServer
path = sys.argv[sys.argv.index('--host') + 1]
class Handler(BaseHTTPRequestHandler):
 def log_message(self, *args): pass
 def do_GET(self): time.sleep(3)
UnixStreamServer(path, Handler).serve_forever()
''')
    backend_files["binary"].chmod(0o700)
    backend_files["binary_sha256"] = _hash(backend_files["binary"])
    real_popen = module.subprocess.Popen
    real_tempdir = module.tempfile.TemporaryDirectory
    processes = []
    tempdirs = []
    request_started = False

    def track_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        socket_path = args[0][args[0].index("--host") + 1]
        ready_by = time.monotonic() + 3
        while not Path(socket_path).exists() and time.monotonic() < ready_by:
            time.sleep(.005)
        assert Path(socket_path).exists()
        return process

    def track_tempdir(*args, **kwargs):
        tempdir = real_tempdir(*args, **kwargs)
        tempdirs.append(tempdir)
        return tempdir

    monkeypatch.setattr(module.subprocess, "Popen", track_popen)
    monkeypatch.setattr(module.tempfile, "TemporaryDirectory", track_tempdir)
    def should_stop():
        return request_started

    backend = LlamaServerBackend(**backend_files, startup_seconds=10,
                                 should_stop=should_stop)
    request_before = backend._request_before

    def cancel_during_health_check(*args, **kwargs):
        nonlocal request_started
        request_started = True
        return request_before(*args, **kwargs)

    monkeypatch.setattr(backend, "_request_before", cancel_during_health_check)
    close_calls = 0
    close = backend.close

    def count_close():
        nonlocal close_calls
        close_calls += 1
        close()

    monkeypatch.setattr(backend, "close", count_close)
    with pytest.raises(LlamaBackendStopped, match="cancelled"), backend:
        pytest.fail("cancelled startup must not enter the backend")
    assert close_calls == 2
    assert processes and processes[0].poll() is not None
    assert tempdirs and not Path(tempdirs[0].name).exists()


def test_close_kills_and_reaps_after_wait_is_interrupted(backend_files, monkeypatch):
    from metis.core import llama_server_backend as module

    class InterruptedProcess:
        pid = 123
        returncode = None

        def poll(self):
            return self.returncode

    process = InterruptedProcess()
    signals = []
    group_alive = True

    def killpg(_pid, value):
        nonlocal group_alive
        signals.append(value)
        if value == 0:
            if group_alive:
                return
            raise ProcessLookupError
        if value == signal.SIGTERM:
            process.returncode = -signal.SIGTERM
        if value == signal.SIGKILL:
            group_alive = False
            process.returncode = -signal.SIGKILL

    def interrupt_sleep(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(module.os, "killpg", killpg)
    monkeypatch.setattr(module.time, "sleep", interrupt_sleep)
    backend = LlamaServerBackend(**backend_files)
    backend._process = process
    with pytest.raises(KeyboardInterrupt):
        backend.close()
    assert signals == [signal.SIGTERM, 0, signal.SIGKILL, 0]
    assert backend._process is None and not group_alive
    backend.close()


def test_close_kills_descendant_that_outlives_wrapper(backend_files, monkeypatch, tmp_path):
    from metis.core import llama_server_backend as module

    class WrapperProcess:
        pid = 456
        returncode = None

        def poll(self):
            return self.returncode

    process = WrapperProcess()
    group_alive = True
    signals = []
    group_probes = 0

    def killpg(_pid, value):
        nonlocal group_alive, group_probes
        signals.append(value)
        if value == 0:
            group_probes += 1
            if group_probes == 1:
                raise PermissionError
            if group_alive:
                return
            raise ProcessLookupError
        if value == signal.SIGTERM:
            # Model a wrapper that exits while a descendant ignores SIGTERM.
            process.returncode = -signal.SIGTERM
        if value == signal.SIGKILL:
            group_alive = False

    monkeypatch.setattr(module.os, "killpg", killpg)
    monkeypatch.setattr(module, "_PROCESS_TERMINATION_GRACE_SECONDS", .01)
    monkeypatch.setattr(module, "_PROCESS_GROUP_POLL_INTERVAL_SECONDS", .001)
    backend = LlamaServerBackend(**backend_files)
    backend._process = process
    private = module.tempfile.TemporaryDirectory(dir=tmp_path)
    private_path = Path(private.name)
    backend._private = private
    backend._socket = str(private_path / "server.sock")

    backend.close()

    assert signals[0] == signal.SIGTERM and signal.SIGKILL in signals
    assert not group_alive and backend._process is None
    assert not private_path.exists()


def test_close_keeps_resources_if_descendant_survives_sigkill(backend_files, monkeypatch, tmp_path):
    from metis.core import llama_server_backend as module

    class WrapperProcess:
        pid = 654
        returncode = -signal.SIGTERM

        def poll(self):
            return self.returncode

    process = WrapperProcess()
    signals = []

    def killpg(_pid, value):
        signals.append(value)
        if value == 0:
            return
        if value == signal.SIGKILL:
            raise PermissionError

    class Log:
        closed = False

        def close(self):
            self.closed = True

    monkeypatch.setattr(module.os, "killpg", killpg)
    monkeypatch.setattr(module, "_PROCESS_TERMINATION_GRACE_SECONDS", 0)
    monkeypatch.setattr(module, "_PROCESS_KILL_REAP_TIMEOUT_SECONDS", 0)
    backend = LlamaServerBackend(**backend_files)
    backend._process = process
    private = module.tempfile.TemporaryDirectory(dir=tmp_path)
    private_path = Path(private.name)
    backend._private = private
    log = Log()
    backend._log = log

    with pytest.raises(LlamaBackendError, match="did not stop"):
        backend.close()

    assert signal.SIGKILL in signals
    assert backend._process is process and backend._private is private
    assert backend._log is log and not log.closed
    assert private_path.exists()


def test_close_waits_through_interrupt_after_sigkill(backend_files, monkeypatch, tmp_path):
    from metis.core import llama_server_backend as module

    class DelayedProcess:
        pid = 987
        returncode = None
        kill_sent = False
        interrupted_poll = False

        def poll(self):
            if self.kill_sent and not self.interrupted_poll:
                self.interrupted_poll = True
                raise KeyboardInterrupt
            return self.returncode

    process = DelayedProcess()
    group_alive = True

    def killpg(_pid, value):
        nonlocal group_alive
        if value == 0:
            if group_alive:
                return
            raise ProcessLookupError
        if value == signal.SIGKILL:
            process.kill_sent = True

    def finish_kill(_seconds):
        nonlocal group_alive
        process.returncode = -signal.SIGKILL
        group_alive = False

    monkeypatch.setattr(module.os, "killpg", killpg)
    monkeypatch.setattr(module.time, "sleep", finish_kill)
    monkeypatch.setattr(module, "_PROCESS_TERMINATION_GRACE_SECONDS", 0)
    monkeypatch.setattr(module, "_PROCESS_GROUP_POLL_INTERVAL_SECONDS", .001)
    backend = LlamaServerBackend(**backend_files)
    backend._process = process
    private = module.tempfile.TemporaryDirectory(dir=tmp_path)
    private_path = Path(private.name)
    backend._private = private

    with pytest.raises(KeyboardInterrupt):
        backend.close()

    assert process.interrupted_poll and not group_alive
    assert backend._process is None and backend._private is None
    assert not private_path.exists()


def test_close_defers_final_poll_and_cleanup_interrupts(backend_files, monkeypatch, tmp_path):
    from metis.core import llama_server_backend as module

    class InterruptedPollProcess:
        pid = 789
        poll_calls = 0

        def poll(self):
            self.poll_calls += 1
            if self.poll_calls == 3:
                raise KeyboardInterrupt
            if self.poll_calls >= 4:
                return -signal.SIGKILL
            return None

    class InterruptOnce:
        def __init__(self):
            self.calls = 0
            self.closed = False

        def close(self):
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt
            self.closed = True

    class PrivateDirectory:
        def __init__(self, path):
            self.name = str(path)
            Path(self.name).mkdir()
            self.calls = 0

        def cleanup(self):
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt
            Path(self.name).rmdir()

    process = InterruptedPollProcess()
    group_alive = True

    def killpg(_pid, value):
        nonlocal group_alive
        if value == 0:
            if group_alive:
                return
            raise ProcessLookupError
        if value == signal.SIGKILL:
            group_alive = False

    monkeypatch.setattr(module.os, "killpg", killpg)
    monkeypatch.setattr(module, "_PROCESS_TERMINATION_GRACE_SECONDS", 0)
    monkeypatch.setattr(module, "_PROCESS_KILL_REAP_TIMEOUT_SECONDS", 0)
    backend = LlamaServerBackend(**backend_files)
    backend._process = process
    log = InterruptOnce()
    private = PrivateDirectory(tmp_path / "private")
    backend._log = log
    backend._private = private
    backend._socket = str(Path(private.name) / "server.sock")

    with pytest.raises(KeyboardInterrupt):
        backend.close()

    assert backend._process is None and backend._log is None and backend._private is None
    assert log.closed and log.calls == 2
    assert private.calls == 2 and not Path(private.name).exists()
    assert not group_alive


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
