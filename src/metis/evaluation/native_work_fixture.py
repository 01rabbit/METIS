"""Exercise one ledger-bound native launch using only the public text fixture."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import socket
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from metis.core.study_token_admission import (
    StudyTokenAdmission,
    TokenAdmissionReceipt,
    TokenLaunchClaim,
    TokenLaunchOutcome,
)
from metis.evaluation.native_build_identity import read_approved_native_build, verify_native_runtime

FIXTURE_MODEL_SHA256 = "270cba1bd5109f42d03350f60406024560464db173c0e387d91f0426d3bd256d"
FIXTURE_PROMPT = "One day, a rabbit ran down the road."
FIXTURE_PROMPT_SHA256 = hashlib.sha256(FIXTURE_PROMPT.encode()).hexdigest()
_TOKENIZATION = json.dumps({"content": FIXTURE_PROMPT, "add_special": True}).encode()
_FIXTURE_TOKEN_IDS = (1, 385, 328, 432, 261, 352, 412, 430, 430, 275, 352, 303, 279, 327, 416, 265, 352, 414, 380, 426)
_FIXTURE_PREFILL_TOKENS = len(_FIXTURE_TOKEN_IDS)
_FIXTURE_STARTUP_TOKENS = 2
_MAX_RESPONSE_BYTES = 65_536
_MAX_RECEIPT_BYTES = 256


@dataclass(frozen=True)
class _FixtureRequest:
    n_predict: int
    end: Literal["limit", "word", "eos"]
    body: bytes
    protocol_sha256: str


def _fixture_request(n_predict: int, end: Literal["limit", "word", "eos"]) -> _FixtureRequest:
    if type(n_predict) is not int or n_predict not in (1, 3):
        raise ValueError("fixture supports output limits 1 and 3")
    if end not in ("limit", "word", "eos") or (end != "limit" and n_predict != 3):
        raise ValueError("invalid public fixture stopping profile")
    body = json.dumps({
        "prompt": FIXTURE_PROMPT, "n_predict": n_predict, "temperature": 0,
        "cache_prompt": False, "stream": False, "ignore_eos": False,
        "stop": [" He"] if end == "word" else [],
        "logit_bias": [[2, 100]] if end == "eos" else [],
    }, sort_keys=True, separators=(",", ":")).encode()
    commitment = hashlib.sha256(b"METIS public fixture sampling v1\n" + body).hexdigest()
    return _FixtureRequest(n_predict, end, body, commitment)


def fixture_protocol_sha256(n_predict: int = 1, *, end: Literal["limit", "word", "eos"] = "limit") -> str:
    """Commit the exact public fixture request in the admission's study pin."""
    return _fixture_request(n_predict, end).protocol_sha256


def _stage(source: Path, destination: Path, expected: str, *, limit: int, executable: bool = False) -> None:
    digest = hashlib.sha256()
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as content, destination.open("xb") as staged:
        info = os.fstat(content.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError("artifact is outside the fixture size or file type boundary")
        remaining = limit
        while chunk := content.read(min(remaining + 1, 1024 * 1024)):
            remaining -= len(chunk)
            if remaining < 0:
                raise ValueError("artifact grew beyond the fixture boundary")
            digest.update(chunk)
            staged.write(chunk)
        if digest.hexdigest() != expected:
            raise ValueError("staged artifact digest does not match admission")
        os.fchmod(staged.fileno(), 0o500 if executable else 0o400)


async def _exchange(path: Path, route: str, body: bytes = b"") -> tuple[int, dict]:
    reader, writer = await asyncio.open_unix_connection(path, limit=_MAX_RESPONSE_BYTES)
    try:
        method = "POST" if body else "GET"
        writer.write(
            f"{method} {route} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body
        )
        await writer.drain()
        head = await reader.readuntil(b"\r\n\r\n")
        status_line, *headers = head[:-4].split(b"\r\n")
        protocol, status, _ = status_line.split(b" ", 2)
        fields = [line.partition(b":") for line in headers]
        lengths = [value.strip() for name, _, value in fields if name.lower() == b"content-length"]
        if (protocol != b"HTTP/1.1" or len(lengths) != 1 or not lengths[0].isdigit()
                or any(name.lower() == b"transfer-encoding" for name, _, _ in fields)):
            raise ValueError("unusable fixture HTTP response")
        length = int(lengths[0])
        if not 0 < length <= _MAX_RESPONSE_BYTES:
            raise ValueError("fixture HTTP response is outside its bound")
        response = json.loads(await reader.readexactly(length), object_pairs_hook=_unique_fields)
        if not isinstance(response, dict):
            raise TypeError("invalid fixture HTTP response")
        return int(status), response
    finally:
        writer.close()
        await writer.wait_closed()


class _FixtureMismatch(ValueError):
    """HTTP observations disagreed with the committed fixture policy."""


async def _complete_once(
    path: Path, process: subprocess.Popen[bytes], seconds: float, request: _FixtureRequest,
) -> int | None:
    async with asyncio.timeout(seconds):
        while process.poll() is None:
            try:
                status, health = await _exchange(path, "/health")
                if status == 200 and health.get("status") == "ok":
                    break
            except (OSError, TypeError, ValueError, RecursionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
                pass
            await asyncio.sleep(0.025)
        else:
            return None
        try:
            status, tokenization = await _exchange(path, "/tokenize", _TOKENIZATION)
        except (OSError, TypeError, ValueError, RecursionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            return None
        tokens = tokenization.get("tokens")
        if (status != 200 or not isinstance(tokens, list)
                or any(type(token) is not int for token in tokens) or tuple(tokens) != _FIXTURE_TOKEN_IDS):
            raise _FixtureMismatch("fixture tokenization mismatch")
        try:
            status, result = await _exchange(path, "/completion", request.body)
        except (OSError, TypeError, ValueError, RecursionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            return None
        generated, evaluated = result.get("tokens_predicted"), result.get("tokens_evaluated")
        settings = result.get("generation_settings")
        expected_stop = [" He"] if request.end == "word" else []
        expected_bias = [{"token": 2, "bias": 100}] if request.end == "eos" else []
        if (status != 200 or not isinstance(settings, dict) or type(evaluated) is not int
                or evaluated != _FIXTURE_PREFILL_TOKENS or type(generated) is not int
                or generated != (request.n_predict if request.end == "limit" else 1)
                or result.get("stop_type") != request.end
                or result.get("stopping_word") != (expected_stop[0] if expected_stop else "")
                or result.get("truncated") is not False or not isinstance(result.get("content"), str)
                or type(settings.get("n_predict")) is not int or settings["n_predict"] != request.n_predict
                or type(settings.get("max_tokens")) is not int or settings["max_tokens"] != request.n_predict
                or settings.get("speculative.types") != "none,none"
                or settings.get("backend_sampling") is not False or settings.get("stream") is not False
                or settings.get("ignore_eos") is not False
                or type(settings.get("temperature")) not in (int, float) or settings["temperature"] != 0
                or settings.get("stop") != expected_stop or settings.get("logit_bias") != expected_bias):
            raise _FixtureMismatch("fixture completion settings or counters mismatch")
        return generated


def _finish_process(
    process: subprocess.Popen[bytes], control: socket.socket, *, command: bytes,
) -> tuple[bool, int | None]:
    result = process.stdout
    assert result is not None
    try:
        if not command:
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                command = b"K"
        if command and process.poll() is None:
            try:
                control.send(command, socket.MSG_NOSIGNAL)
            except (BrokenPipeError, ConnectionResetError):
                pass
    finally:
        control.close()
    try:
        if process.wait(timeout=3) != 0:
            return False, None
        line = result.read(8)
        return True, int(line) if line else None
    except (subprocess.TimeoutExpired, ValueError):
        return False, None
    finally:
        result.close()


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("duplicate receipt fields")
    return fields


def _receipt_outcome(
    fd: int, claim: TokenLaunchClaim, status: int, generated: int | None, native_cap: int,
) -> TokenLaunchOutcome:
    invalid = TokenLaunchOutcome(status="receipt_invalid", exit_status=status)
    try:
        os.set_blocking(fd, False)
        raw = os.read(fd, _MAX_RECEIPT_BYTES + 1)
        if len(raw) > _MAX_RECEIPT_BYTES or raw.count(b"\n") != 1 or not raw.endswith(b"\n") or os.read(fd, 1):
            return invalid
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_fields)
    except (OSError, ValueError):
        return invalid
    if (not isinstance(value, dict) or set(value) != {"version", "nonce", "cap", "charged", "reason"}
            or type(value["version"]) is not int or value["version"] != 1 or value["nonce"] != claim.nonce
            or type(value["cap"]) is not int or value["cap"] != native_cap
            or type(value["charged"]) is not int or not 0 <= value["charged"] <= value["cap"]):
        return invalid
    reason, charged = value["reason"], value["charged"]
    if (reason == "shutdown" and status == 0 and generated is not None
            and charged >= _FIXTURE_STARTUP_TOKENS + _FIXTURE_PREFILL_TOKENS + generated - 1
            and charged + generated <= claim.receipt.attempt.tokens):
        return TokenLaunchOutcome(status="completed", exit_status=status, observed_work=charged)
    if reason == "cap_denied" and status == 75 and generated is None:
        return TokenLaunchOutcome(status="cap_denied", exit_status=status, observed_work=charged)
    if reason == "unsupported_graph" and status == 75 and generated is None:
        return TokenLaunchOutcome(status="unsupported_graph", exit_status=status, observed_work=charged)
    if reason == "server_error" and 1 <= status <= 255 and status not in (74, 75) and generated is None:
        return TokenLaunchOutcome(status="server_error", exit_status=status, observed_work=charged)
    return invalid


def _run_claim(
    claim: TokenLaunchClaim, binary: Path, model: Path, socket_path: Path,
    seconds: float, request: _FixtureRequest, native_cap: int,
) -> TokenLaunchOutcome:
    try:
        read_fd, write_fd = os.pipe()
    except OSError:
        return TokenLaunchOutcome(status="launch_failed")
    try:
        control_parent, control_child = socket.socketpair()
        try:
            process = subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).with_name("_fixture_guardian.py")), str(write_fd),
                 str(binary), "--metis-work-budget", str(native_cap), "--model", str(model),
                 "--socket", str(socket_path), "--metis-receipt-fd", str(write_fd), "--metis-launch-nonce", claim.nonce],
                stdin=control_child.fileno(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                pass_fds=(write_fd,),
                bufsize=0,
                start_new_session=True, env={"PATH": os.defpath, "LANG": "C", "TMPDIR": str(socket_path.parent)},
            )
        except OSError:
            control_parent.close()
            return TokenLaunchOutcome(status="launch_failed")
        finally:
            control_child.close()
            os.close(write_fd)

        generated = None
        interrupted: Literal["timeout", "cancelled"] | None = None
        mismatch = False
        try:
            generated = asyncio.run(_complete_once(socket_path, process, seconds, request))
        except _FixtureMismatch:
            mismatch = True
        except TimeoutError:
            interrupted = "timeout"
        except KeyboardInterrupt:
            interrupted = "cancelled"
        finally:
            finished, status = _finish_process(
                process, control_parent,
                command=b"K" if interrupted else b"T" if generated is not None else b"",
            )

        if not finished:
            return TokenLaunchOutcome(status="lost")
        if interrupted is not None:
            return TokenLaunchOutcome(status=interrupted, exit_status=status)
        if status is None:
            return TokenLaunchOutcome(status="launch_failed")
        if mismatch:
            return TokenLaunchOutcome(status="receipt_invalid", exit_status=status)
        return _receipt_outcome(read_fd, claim, status, generated, native_cap)
    finally:
        os.close(read_fd)


def qualify_native_launch(
    admission: StudyTokenAdmission, receipt: TokenAdmissionReceipt, *,
    binary: Path, model: Path, manifest: Path, expected_manifest_sha256: str, patch: Path,
    seconds: float = 10,
    n_predict: int = 1, end: Literal["limit", "word", "eos"] = "limit",
) -> TokenLaunchOutcome:
    """Run one fixed public fixture request. The admission is never refunded."""
    receipt = TokenAdmissionReceipt.model_validate(receipt)
    if (receipt.study.model_sha256 != FIXTURE_MODEL_SHA256
            or receipt.attempt.prompt_sha256 != FIXTURE_PROMPT_SHA256):
        raise ValueError("only the registered single-file public fixture is supported")
    request = _fixture_request(n_predict, end)
    if receipt.study.protocol_sha256 != request.protocol_sha256:
        raise ValueError("public fixture sampling profile does not match admission")
    # Charge every allowed sampled output separately, including the last
    # token that can leave the API without entering another model graph.
    native_cap = receipt.attempt.tokens - request.n_predict
    if native_cap <= 0:
        raise ValueError("admission leaves no positive native cap after output headroom")
    if not 0 < seconds <= 30:
        raise ValueError("fixture deadline is outside its bound")

    if (receipt.study.native_manifest_sha256 is None
            or expected_manifest_sha256 != receipt.study.native_manifest_sha256):
        raise ValueError("native manifest approval does not match committed study pin")
    approved = read_approved_native_build(
        manifest, expected_manifest_sha256=expected_manifest_sha256, patch=patch,
        target_os=platform.system(), target_arch=platform.machine(),
    )
    if receipt.study.runtime_sha256 != approved.binary_sha256:
        raise ValueError("native approval does not match committed runtime pin")

    with tempfile.TemporaryDirectory(prefix="metis-native-", dir="/tmp") as folder:
        root = Path(folder).resolve()
        staged_binary, staged_model = root / "server", root / "fixture.gguf"
        _stage(binary, staged_binary, approved.binary_sha256, limit=128 * 1024**2, executable=True)
        # The digest identifies the entire registered single-file GGUF. Other
        # file layouts, including split GGUFs, cannot reach launch.
        _stage(model, staged_model, FIXTURE_MODEL_SHA256, limit=2 * 1024**2)
        verify_native_runtime(approved, binary=staged_binary, model=staged_model)
        with admission.claim_fixture_launch(receipt) as claim:
            outcome = _run_claim(claim, staged_binary, staged_model, root / "server.sock", seconds, request, native_cap)
            outcome = outcome.model_copy(update={"native_manifest_sha256": expected_manifest_sha256})
            admission.record_outcome(claim, outcome)
            return outcome
