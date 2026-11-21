#!/usr/bin/env python3
"""Run one bounded, answer-free trace against the public stories260K fixture."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import platform
import resource
import secrets
import signal
import socket
import stat
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from types import FrameType
from typing import Any

from metis.evaluation.native_work_trace import (
    PUBLIC_FIXTURE_SHA256,
    NativeWorkTrace,
    evaluate_work_bound,
    expand_prompt_to_token_budget,
    parse_trace,
    validate_retry_probe,
    verify_build_manifest,
)

PROMPT = "One day, a rabbit ran down the road."
CONTEXT_SIZE = 4096
N_PREDICT = 3
DEFAULT_EDGE_OFFSETS = (0, 1, 8)
DEFAULT_EDGE_SEED = 20261121
MAX_MODEL_BYTES = 64 * 1024 * 1024
MAX_LOG_BYTES = 4 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024


class _TraceTerminated(Exception):
    pass


class _Termination:
    def __init__(self) -> None:
        self.requested = False
        self.waiting = False

    def handle(self, _signum: int, _frame: FrameType | None) -> None:
        if not self.requested:
            self.requested = True
            if self.waiting:
                raise _TraceTerminated

    @contextmanager
    def interrupt_wait(self) -> Iterator[None]:
        try:
            self.waiting = True
            if self.requested:
                raise _TraceTerminated
            yield
        finally:
            self.waiting = False


@contextmanager
def _handle_termination() -> Iterator[_Termination]:
    termination = _Termination()
    previous = signal.signal(signal.SIGTERM, termination.handle)
    try:
        yield termination
    finally:
        signal.signal(signal.SIGTERM, previous)
    if termination.requested:
        raise _TraceTerminated


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: Path, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self.path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(self.path))


def _popen_with_bounded_file_size(args: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
    previous = resource.getrlimit(resource.RLIMIT_FSIZE)
    soft, hard = previous
    ceiling = MAX_LOG_BYTES if hard == resource.RLIM_INFINITY else min(MAX_LOG_BYTES, hard)
    inherited_soft = ceiling if soft == resource.RLIM_INFINITY else min(soft, ceiling)
    resource.setrlimit(resource.RLIMIT_FSIZE, (inherited_soft, hard))
    try:
        return subprocess.Popen(args, **kwargs)
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, previous)


def sha256_model(path: Path) -> str:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_MODEL_BYTES:
            raise ValueError("public model fixture is outside its file/size boundary")
        digest = hashlib.sha256()
        total = 0
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_MODEL_BYTES:
                    raise ValueError("public model fixture exceeded its size boundary")
                digest.update(chunk)
        if total != info.st_size:
            raise ValueError("public model fixture changed while hashing")
        return digest.hexdigest()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def request(socket_path: Path, route: str, payload: dict[str, Any] | None,
            *, timeout: float, allow_error: bool = False) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    with closing(UnixConnection(socket_path, timeout)) as connection:
        connection.request("GET" if body is None else "POST", route, body=body,
                           headers={} if body is None else {"Content-Type": "application/json"})
        with connection.getresponse() as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("native trace response exceeded size boundary")
            if response.status != 200 and not allow_error:
                raise ValueError("native trace request failed")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise TypeError("native trace response is invalid")
            return response.status, value


def wait_ready(process: subprocess.Popen[bytes], socket_path: Path, *, deadline: float) -> None:
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ValueError("pinned trace server exited before readiness")
        try:
            _, value = request(socket_path, "/health", None, timeout=0.5)
            if value.get("status") == "ok":
                return
        except (OSError, TimeoutError, http.client.HTTPException, ValueError, json.JSONDecodeError):
            pass
        time.sleep(0.1)
    raise TimeoutError("pinned trace server readiness deadline exceeded")


def _stop(process: subprocess.Popen[bytes]) -> int:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        return process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return process.wait(timeout=5)


def _verify_binary_and_model(binary: Path, model: Path) -> tuple[Path, Path, Any, str]:
    binary = binary.resolve(strict=True)
    model = model.resolve(strict=True)
    build_root = binary.parent.parent.parent
    patch = build_root / "llama-work-trace.patch"
    manifest = verify_build_manifest(build_root / "trace-build.json", binary=binary, patch=patch)
    if (manifest.target_os != platform.system() or manifest.target_arch != platform.machine()):
        raise ValueError("trace build target does not match this host")
    model_sha256 = sha256_model(model)
    if model_sha256 != PUBLIC_FIXTURE_SHA256:
        raise ValueError("model is not the registered public trace fixture")
    return binary, model, manifest, model_sha256


def _execute_trace_run(binary: Path, model: Path, *, inject_one_retry: bool,
                       termination: _Termination,
                       interact: Any) -> tuple[Any, NativeWorkTrace]:
    """Start the pinned server once, run ``interact(socket_path)`` under SIGTERM
    deferral, stop cleanly, and return its result with the parsed aggregate trace."""
    nonce = secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix="metis-llama-trace-") as temp:
        root = Path(temp)
        os.chmod(root, 0o700)
        socket_path = root / "server.sock"
        log_path = root / "server.log"
        if socket_path.exists():
            raise ValueError("private trace socket unexpectedly exists")
        environment = {
            "PATH": os.defpath, "HOME": str(root), "TMPDIR": str(root), "LANG": "C",
            "METIS_LLAMA_TRACE_NONCE": nonce,
        }
        if inject_one_retry:
            environment["METIS_LLAMA_TRACE_INJECT_RETRY_ONCE"] = "1"
        with log_path.open("w+b") as log:
            process = _popen_with_bounded_file_size(
                [str(binary), "--model", str(model), "--host", str(socket_path),
                 "--parallel", "1", "--ctx-size", str(CONTEXT_SIZE), "--batch-size", "512",
                 "--ubatch-size", "128", "--no-webui", "--no-warmup", "--no-context-shift"],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=environment,
                close_fds=True, start_new_session=True,
            )
            try:
                # Defer SIGTERM while acquiring and releasing the child process.
                with termination.interrupt_wait():
                    wait_ready(process, socket_path, deadline=time.monotonic() + 60)
                    result = interact(socket_path)
            finally:
                exit_code = _stop(process)
            if exit_code != 0:
                raise ValueError("pinned trace server did not stop cleanly")
            log.seek(0)
            stderr = log.read(MAX_LOG_BYTES + 1)
            if len(stderr) > MAX_LOG_BYTES:
                raise ValueError("pinned trace log exceeded size boundary")

    return result, parse_trace(stderr, expected_nonce=nonce)


def run(binary: Path, model: Path, *, inject_one_retry: bool) -> dict[str, Any]:
    resolved_binary, resolved_model, manifest, model_sha256 = _verify_binary_and_model(binary, model)

    def interact(socket_path: Path) -> dict[str, Any]:
        status, response = request(
            socket_path, "/completion",
            {"prompt": PROMPT, "n_predict": N_PREDICT, "temperature": 0,
             "cache_prompt": False}, timeout=30,
        )
        evaluated = response.get("tokens_evaluated")
        predicted = response.get("tokens_predicted")
        if (status != 200 or isinstance(evaluated, bool) or not isinstance(evaluated, int)
                or evaluated <= 0 or isinstance(predicted, bool) or not isinstance(predicted, int)
                or not 0 <= predicted <= N_PREDICT):
            raise ValueError("pinned trace response did not contain bounded token counts")
        return {"http_status": status, "tokens_evaluated": evaluated, "tokens_predicted": predicted}

    with _handle_termination() as termination:
        result, trace = _execute_trace_run(
            resolved_binary, resolved_model, inject_one_retry=inject_one_retry,
            termination=termination, interact=interact)

    validate_retry_probe(trace, injected=inject_one_retry)

    # Intentionally retain no prompt text, generated output, or raw process logs.
    return {
        "version": 1,
        "source_commit": manifest.source_commit,
        "trace_patch_sha256": manifest.trace_patch_sha256,
        "binary_sha256": manifest.binary_sha256,
        "model_sha256": model_sha256,
        "profile": {
            "context_size": CONTEXT_SIZE,
            "n_predict": N_PREDICT,
            "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
            "injected_memory_prepare_failure": inject_one_retry,
        },
        "response": {"http_status": result["http_status"],
                     "tokens_evaluated": result["tokens_evaluated"],
                     "tokens_predicted": result["tokens_predicted"]},
        "trace": trace.model_dump(mode="json"),
        "hard_token_budget_enforced": False,
        "heldout_eligible": False,
    }


def _read_effective_n_ctx(socket_path: Path) -> int:
    """Read the server's effective per-slot context from /props (patch-unchanged)."""
    _, props = request(socket_path, "/props", None, timeout=5)
    settings = props.get("default_generation_settings")
    candidate = settings.get("n_ctx") if isinstance(settings, dict) else None
    if isinstance(candidate, bool) or not isinstance(candidate, int):
        candidate = props.get("n_ctx")
    if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 1:
        raise ValueError("pinned trace server did not report a positive effective context")
    return candidate


def _tokenize_count(socket_path: Path, text: str) -> int:
    _, value = request(socket_path, "/tokenize", {"content": text}, timeout=10)
    tokens = value.get("tokens")
    if not isinstance(tokens, list):
        raise TypeError("pinned trace server returned an invalid tokenization")
    return len(tokens)


def _require_clean_startup(trace: NativeWorkTrace) -> None:
    startup = trace.startup
    if (startup.process_failures or startup.graph_failures or startup.graph_pre_dispatch_failures
            or startup.server_batch_retries or startup.memory_prepare_failures
            or startup.injected_memory_prepare_failures):
        raise ValueError("context-edge trace recorded an unexpected startup failure")


def run_context_edge(binary: Path, model: Path, *, edge_offsets: tuple[int, ...],
                     n_predict: int, seed: int) -> dict[str, Any]:
    resolved_binary, resolved_model, manifest, model_sha256 = _verify_binary_and_model(binary, model)
    cells: list[dict[str, Any]] = []
    with _handle_termination() as termination:
        for offset in edge_offsets:
            def interact(socket_path: Path, offset: int = offset) -> dict[str, Any]:
                effective = _read_effective_n_ctx(socket_path)
                target = max(effective - offset, 1)
                prompt = expand_prompt_to_token_budget(
                    target, lambda text: _tokenize_count(socket_path, text), seed=seed)
                requested = _tokenize_count(socket_path, prompt)
                status, response = request(
                    socket_path, "/completion",
                    {"prompt": prompt, "n_predict": n_predict, "temperature": 0,
                     "cache_prompt": False}, timeout=60, allow_error=True)
                evaluated = response.get("tokens_evaluated")
                predicted = response.get("tokens_predicted")
                return {
                    "offset": offset, "effective_n_ctx": effective,
                    "requested_prompt_tokens": requested, "http_status": status,
                    "tokens_evaluated": evaluated if isinstance(evaluated, int)
                    and not isinstance(evaluated, bool) else None,
                    "tokens_predicted": predicted if isinstance(predicted, int)
                    and not isinstance(predicted, bool) else None,
                }

            result, trace = _execute_trace_run(
                resolved_binary, resolved_model, inject_one_retry=False,
                termination=termination, interact=interact)
            _require_clean_startup(trace)
            evaluation = evaluate_work_bound(
                trace, effective_n_ctx=result["effective_n_ctx"], n_predict=n_predict)
            cells.append({
                **result,
                "bound": evaluation.bound,
                "observed_graph_positions": evaluation.observed_graph_positions,
                "falsified": evaluation.falsified,
                "startup": trace.startup.model_dump(mode="json"),
                "requests": trace.requests.model_dump(mode="json"),
            })

    bound_falsified = any(cell["falsified"] for cell in cells)
    # Intentionally retain only counts, token counts, and digests — never prompt text.
    return {
        "version": 1,
        "mode": "context-edge",
        "source_commit": manifest.source_commit,
        "trace_patch_sha256": manifest.trace_patch_sha256,
        "binary_sha256": manifest.binary_sha256,
        "model_sha256": model_sha256,
        "profile": {
            "context_size": CONTEXT_SIZE,
            "n_predict": n_predict,
            "edge_offsets": list(edge_offsets),
            "seed": seed,
        },
        "cells": cells,
        "bound_falsified": bound_falsified,
        "hard_token_budget_enforced": False,
        "heldout_eligible": False,
    }


def _write_new(path: Path, data: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    temporary = Path(temporary_name)
    target_created = False
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as destination:
            destination.write(data)
            destination.flush()
            os.fsync(descriptor)

        # Linking a fully written same-directory temporary file publishes it
        # atomically and fails if the requested output already exists.
        os.link(temporary, path, follow_symlinks=False)
        target_created = True
        source_stat = os.fstat(descriptor)
        target_stat = os.stat(path, follow_symlinks=False)
        if (source_stat.st_dev, source_stat.st_ino) != (target_stat.st_dev, target_stat.st_ino):
            raise OSError("published trace receipt identity changed")
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        if target_created:
            try:
                source_stat = os.fstat(descriptor)
                target_stat = os.stat(path, follow_symlinks=False)
                if (source_stat.st_dev, source_stat.st_ino) == (target_stat.st_dev, target_stat.st_ino):
                    os.unlink(path)
            except FileNotFoundError:
                pass
        raise
    finally:
        os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _parse_offsets(raw: str) -> tuple[int, ...]:
    unique: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        offset = int(part)
        if not 0 <= offset <= CONTEXT_SIZE:
            raise ValueError("context-edge offset is out of range")
        if offset not in unique:
            unique.append(offset)
    if not unique:
        raise ValueError("no context-edge offsets were provided")
    return tuple(unique)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("--inject-one-retry", action="store_true",
                        help="inject one synthetic memory-prepare refusal after readiness")
    parser.add_argument("--context-edge", action="store_true",
                        help="run reproducible context-edge cells and measure graph work per cell")
    parser.add_argument("--edge-offsets", default=",".join(str(o) for o in DEFAULT_EDGE_OFFSETS),
                        help="comma-separated token offsets below the effective context (default 0,1,8)")
    parser.add_argument("--n-predict", type=int, default=N_PREDICT,
                        help="output token cap per context-edge request")
    parser.add_argument("--seed", type=int, default=DEFAULT_EDGE_SEED,
                        help="deterministic prompt seed for context-edge calibration")
    parser.add_argument("--falsify-bound", action="store_true",
                        help="exit non-zero if any context-edge cell has M > n_ctx*(n_predict+1)")
    parser.add_argument("--output", type=Path,
                        help="create a new 0600 JSON file with aggregate-only evidence")
    args = parser.parse_args()
    if args.falsify_bound and not args.context_edge:
        parser.error("--falsify-bound requires --context-edge")
    if args.context_edge and args.inject_one_retry:
        parser.error("--context-edge cannot be combined with --inject-one-retry")
    offsets: tuple[int, ...] = ()
    if args.context_edge:
        if not 0 <= args.n_predict <= 10**6:
            parser.error("--n-predict is out of range")
        try:
            offsets = _parse_offsets(args.edge_offsets)
        except ValueError as exc:
            parser.error(str(exc))
    try:
        if args.context_edge:
            value = run_context_edge(args.binary, args.model, edge_offsets=offsets,
                                     n_predict=args.n_predict, seed=args.seed)
        else:
            value = run(args.binary, args.model, inject_one_retry=args.inject_one_retry)
    except _TraceTerminated:
        return 128 + signal.SIGTERM
    data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if args.output is None:
        print(data.decode(), end="")
    else:
        _write_new(args.output, data)
        print(json.dumps({"status": "written", "path": str(args.output)}))
    if args.falsify_bound and value.get("bound_falsified"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
