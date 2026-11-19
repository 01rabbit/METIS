"""Experimental, fail-closed llama-server Unix-socket call boundary.

This is a controlled-process primitive, not an advertised hard-cap provider.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import signal
import socket
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Self, TypeGuard

from metis.core.token_reservation import FULL_CONTEXT_RESERVATION_TOKENS


class LlamaBackendError(RuntimeError):
    """Sanitized backend failure; never includes prompts or model output."""


class LlamaBackendStopped(LlamaBackendError):
    """Caller cancelled the live server request."""


class LlamaBackendRefused(LlamaBackendError):
    """The bounded request was rejected before completion could be sent."""


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self.path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def _sha256(path: Path, *, abort_check: Callable[[], None] | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            if abort_check is not None:
                abort_check()
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    if abort_check is not None:
        abort_check()
    return digest.hexdigest()


def _integer(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


class LlamaServerBackend:
    """Own one pinned process and reserve its worst-case calls in shared SQLite.

    The caller supplies one stable budget key and cap shared by all processes.
    An interrupted call consumes its entire reservation. The backend deliberately
    exposes ``hard_cap_capable=False`` until integrated concurrency evidence exists.
    """

    hard_cap_capable = False

    def __init__(self, *, binary: Path, binary_sha256: str, model: Path,
                 model_sha256: str, database: Path, budget_key: str,
                 token_limit: int, max_output_tokens: int, startup_seconds: float = 30,
                 context_reservation: bool = False, startup_deadline: float | None = None,
                 startup_should_stop: Callable[[], bool] | None = None):
        if not budget_key or len(budget_key) > 128 or not 1 <= token_limit <= 10**9:
            raise ValueError("invalid budget configuration")
        if not 1 <= max_output_tokens <= 4096 or not 0 < startup_seconds <= 120:
            raise ValueError("invalid process configuration")
        self.binary, self.model, self.database = binary.resolve(), model.resolve(), database
        self.binary_sha256, self.model_sha256 = binary_sha256, model_sha256
        self.budget_key, self.token_limit = budget_key, token_limit
        self.max_output_tokens, self.startup_seconds = max_output_tokens, startup_seconds
        self.context_reservation = context_reservation
        self.startup_deadline = startup_deadline
        self.startup_should_stop = startup_should_stop
        self._process: subprocess.Popen[bytes] | None = None
        self._private: tempfile.TemporaryDirectory[str] | None = None
        self._log: Any = None
        self._socket: str | None = None

    def __enter__(self) -> Self:
        if self._process is not None or self._private is not None:
            raise LlamaBackendError("server already started")
        deadline = time.monotonic() + self.startup_seconds
        deadline_error = "server startup timed out"
        if self.startup_deadline is not None and self.startup_deadline <= deadline:
            deadline = self.startup_deadline
            deadline_error = "model call deadline exceeded during server startup"
        for path, expected in ((self.binary, self.binary_sha256), (self.model, self.model_sha256)):
            self._check_startup_abort(deadline, deadline_error)
            if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
                raise LlamaBackendError("pinned artifact unavailable")
            if len(expected) != 64 or _sha256(
                    path, abort_check=lambda: self._check_startup_abort(deadline, deadline_error)
            ) != expected.lower():
                raise LlamaBackendError("pinned artifact changed")
        self._check_startup_abort(deadline, deadline_error)
        try:
            self._private = tempfile.TemporaryDirectory(prefix="metis-llama-", dir=None)
            os.chmod(self._private.name, 0o700)
            self._socket = str(Path(self._private.name) / "server.sock")
            self._log = open(os.devnull, "wb")
            # Never inherit LLAMA_ARG_* (draft model, context shift, warmup,
            # endpoints, etc.) or proxy/plugin environment from the parent.
            # The child receives no prompt before complete() reserves tokens.
            child_env = {"PATH": "/usr/bin:/bin", "HOME": self._private.name,
                         "TMPDIR": self._private.name, "LANG": "C"}
            self._check_startup_abort(deadline, deadline_error)
            self._process = subprocess.Popen(
                [str(self.binary), "--model", str(self.model), "--host", self._socket,
                 "--parallel", "1", "--no-webui", "--ctx-size",
                 str(FULL_CONTEXT_RESERVATION_TOKENS),
                 "--no-context-shift", "--no-warmup"],
                stdin=subprocess.DEVNULL, stdout=self._log, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True, env=child_env,
            )
            while time.monotonic() < deadline:
                self._check_startup_abort(deadline, deadline_error)
                if self._process.poll() is not None:
                    raise LlamaBackendError("server exited during startup")
                try:
                    response = self._request_before("/health", None, deadline=deadline,
                                                    should_stop=self.startup_should_stop,
                                                    deadline_error=deadline_error)
                    if response.get("status") == "ok":
                        self._check_startup_abort(deadline, deadline_error)
                        return self
                except LlamaBackendStopped:
                    raise
                except (LlamaBackendError, OSError, TimeoutError) as exc:
                    if isinstance(exc, LlamaBackendError) and str(exc) == deadline_error:
                        raise
                time.sleep(min(.1, max(0, deadline - time.monotonic())))
            raise LlamaBackendError(deadline_error)
        except BaseException:
            self.close()
            raise

    def _check_startup_abort(self, deadline: float, deadline_error: str) -> None:
        if self.startup_should_stop is not None and self.startup_should_stop():
            raise LlamaBackendStopped("model call cancelled during server startup")
        if time.monotonic() >= deadline:
            raise LlamaBackendError(deadline_error)

    def _request(self, route: str, payload: dict[str, Any] | None, *, timeout: float) -> dict[str, Any]:
        if self._socket is None or self._process is None or self._process.poll() is not None:
            raise LlamaBackendError("server unavailable")
        body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
        connection = _UnixConnection(self._socket, timeout)
        try:
            connection.request("POST" if body is not None else "GET", route, body,
                               {"Content-Type": "application/json"} if body is not None else {})
            response = connection.getresponse()
            raw = response.read(1024 * 1024 + 1)
            if response.status != 200 or len(raw) > 1024 * 1024:
                raise LlamaBackendError("server rejected bounded request")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise LlamaBackendError("invalid server response")
            return value
        except (OSError, TimeoutError, json.JSONDecodeError, http.client.HTTPException) as exc:
            raise LlamaBackendError("server request failed") from exc
        finally:
            connection.close()

    def _request_before(self, route: str, payload: dict[str, Any] | None,
                        *, deadline: float, should_stop: Callable[[], bool] | None = None,
                        deadline_error: str = "model call deadline exceeded") -> dict[str, Any]:
        """Enforce one monotonic deadline even if a peer trickles bytes forever."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            self.close()
            raise LlamaBackendError(deadline_error)
        result: list[tuple[dict[str, Any], float]] = []
        errors: list[tuple[BaseException, float]] = []

        def invoke() -> None:
            try:
                result.append((self._request(route, payload, timeout=remaining), time.monotonic()))
            except (LlamaBackendError, OSError, TimeoutError, ValueError) as exc:
                errors.append((exc, time.monotonic()))

        worker = threading.Thread(target=invoke, name="metis-llama-request", daemon=True)
        worker.start()
        while worker.is_alive():
            if should_stop is not None and should_stop():
                self.close()
                raise LlamaBackendStopped("model call cancelled")
            worker.join(timeout=min(.05, max(0, deadline - time.monotonic())))
            if time.monotonic() >= deadline:
                break
        if worker.is_alive():
            self.close()
            raise LlamaBackendError(deadline_error)
        if ((errors and errors[0][1] >= deadline)
                or (result and result[0][1] >= deadline)):
            self.close()
            raise LlamaBackendError(deadline_error)
        if errors:
            raise errors[0][0]
        if not result:
            raise LlamaBackendError("server request produced no result")
        return result[0][0]

    def _reserve(self, amount: int) -> None:
        with sqlite3.connect(self.database, timeout=10, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS llama_token_budgets ("
                       "budget_key TEXT PRIMARY KEY, token_limit INTEGER NOT NULL, reserved INTEGER NOT NULL)")
            row = db.execute("SELECT token_limit, reserved FROM llama_token_budgets WHERE budget_key=?",
                             (self.budget_key,)).fetchone()
            if row is None:
                db.execute("INSERT INTO llama_token_budgets VALUES (?, ?, ?)",
                           (self.budget_key, self.token_limit, amount))
            else:
                if row[0] != self.token_limit or row[1] + amount > self.token_limit:
                    raise LlamaBackendError("shared token budget exhausted or changed")
                db.execute("UPDATE llama_token_budgets SET reserved=reserved+? WHERE budget_key=?",
                           (amount, self.budget_key))
            if amount > self.token_limit:
                raise LlamaBackendError("shared token budget exhausted")
            db.commit()

    def complete(self, prompt: str, *, n_predict: int, timeout_seconds: float,
                 should_stop: Callable[[], bool] | None = None,
                 call_deadline: float | None = None) -> tuple[str, int, int]:
        if not isinstance(prompt, str) or len(prompt.encode()) > 65_536:
            raise ValueError("prompt exceeds input boundary")
        if not 1 <= n_predict <= self.max_output_tokens or not 0 < timeout_seconds <= 120:
            raise ValueError("call exceeds configured boundary")
        if should_stop is not None and should_stop():
            self.close()
            raise LlamaBackendStopped("model call cancelled")
        deadline = time.monotonic() + timeout_seconds
        if call_deadline is not None:
            deadline = min(deadline, call_deadline)
        if deadline <= time.monotonic():
            raise LlamaBackendError("model call deadline exceeded")
        tokenized = self._request_before("/tokenize",
                                         {"content": prompt, "add_special": True}, deadline=deadline,
                                         should_stop=should_stop)
        tokens = tokenized.get("tokens")
        if not isinstance(tokens, list) or not tokens or len(tokens) > self.token_limit:
            raise LlamaBackendError("unusable prompt token count")
        prompt_count = len(tokens)
        if self.context_reservation and prompt_count > FULL_CONTEXT_RESERVATION_TOKENS:
            raise LlamaBackendError("prompt exceeds reserved context")
        # In conservative mode, reserve the complete configured context before
        # inference. This is independent of /tokenize parity. The extra output
        # allowance covers a server that evaluates generated tokens separately.
        reserved_input = FULL_CONTEXT_RESERVATION_TOKENS if self.context_reservation else prompt_count
        self._reserve(reserved_input + n_predict)
        if should_stop is not None and should_stop():
            self.close()
            raise LlamaBackendStopped("model call cancelled")
        # Reservation is permanent from here, even when the request is interrupted.
        try:
            result = self._request_before("/completion", {"prompt": prompt, "n_predict": n_predict,
                               "temperature": 0, "cache_prompt": False}, deadline=deadline,
                                          should_stop=should_stop)
        except BaseException:
            self.close()
            raise
        evaluated, predicted = result.get("tokens_evaluated"), result.get("tokens_predicted")
        settings = result.get("generation_settings")
        if (not _integer(evaluated)
                or (evaluated > FULL_CONTEXT_RESERVATION_TOKENS
                    if self.context_reservation else evaluated != prompt_count)
                or not _integer(predicted)
                or predicted > n_predict or not isinstance(settings, dict)
                or settings.get("n_predict") != n_predict or result.get("model") != str(self.model)
                or not isinstance(result.get("content"), str)):
            self.close()
            raise LlamaBackendError("completion usage or settings mismatch")
        if should_stop is not None and should_stop():
            self.close()
            raise LlamaBackendStopped("model call cancelled")
        return result["content"], evaluated, predicted

    def complete_admitted(self, prompt: str, *, n_predict: int, token_cap: int,
                          timeout_seconds: float,
                          should_stop: Callable[[], bool] | None = None,
                          call_deadline: float | None = None) -> tuple[str, int, int]:
        """Run a claim-funded request without the standalone budget ledger.

        The caller has already consumed a durable study claim. The entire
        conservative context plus sampled-output allowance must fit that claim
        before completion is sent. No failure refunds the claim.
        """
        if not isinstance(prompt, str) or len(prompt.encode()) > 65_536:
            raise LlamaBackendRefused("prompt exceeds input boundary")
        if (not self.context_reservation or not 1 <= n_predict <= self.max_output_tokens
                or not 0 < timeout_seconds <= 120):
            raise LlamaBackendRefused("admitted call exceeds configured boundary")
        required = FULL_CONTEXT_RESERVATION_TOKENS + n_predict
        if required > token_cap:
            raise LlamaBackendRefused("admission cannot cover conservative call reservation")
        if should_stop is not None and should_stop():
            self.close()
            raise LlamaBackendStopped("model call cancelled")
        deadline = time.monotonic() + timeout_seconds
        if call_deadline is not None:
            deadline = min(deadline, call_deadline)
        if deadline <= time.monotonic():
            raise LlamaBackendError("model call deadline exceeded")
        try:
            tokenized = self._request_before("/tokenize", {"content": prompt, "add_special": True},
                                             deadline=deadline, should_stop=should_stop)
        except LlamaBackendStopped:
            raise
        except Exception as exc:
            if isinstance(exc, LlamaBackendError) and "deadline" in str(exc):
                raise
            raise LlamaBackendRefused("prompt tokenization failed") from exc
        tokens = tokenized.get("tokens")
        if (not isinstance(tokens, list) or not tokens
                or len(tokens) > FULL_CONTEXT_RESERVATION_TOKENS):
            raise LlamaBackendRefused("prompt exceeds reserved context")
        if should_stop is not None and should_stop():
            self.close()
            raise LlamaBackendStopped("model call cancelled")
        try:
            result = self._request_before("/completion", {"prompt": prompt, "n_predict": n_predict,
                                         "temperature": 0, "cache_prompt": False},
                                         deadline=deadline, should_stop=should_stop)
        except BaseException:
            self.close()
            raise
        evaluated, predicted = result.get("tokens_evaluated"), result.get("tokens_predicted")
        settings = result.get("generation_settings")
        if (not _integer(evaluated) or evaluated > FULL_CONTEXT_RESERVATION_TOKENS
                or not _integer(predicted) or predicted > n_predict or not isinstance(settings, dict)
                or settings.get("n_predict") != n_predict or result.get("model") != str(self.model)
                or not isinstance(result.get("content"), str)):
            self.close()
            raise LlamaBackendError("completion usage or settings mismatch")
        return result["content"], evaluated, predicted

    def close(self) -> None:
        process = self._process
        self._process = None
        try:
            if process is not None:
                # The group can outlive a wrapper parent; signal it regardless of poll().
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
        finally:
            if self._log is not None:
                self._log.close()
                self._log = None
            if self._private is not None:
                self._private.cleanup()
                self._private = None
                self._socket = None

    def __exit__(self, *_: object) -> None:
        self.close()
