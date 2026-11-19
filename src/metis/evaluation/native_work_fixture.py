"""Exercise one ledger-bound native launch using only the public text fixture."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from metis.core.study_token_admission import (
    StudyTokenAdmission,
    TokenAdmissionReceipt,
    TokenLaunchClaim,
    TokenLaunchOutcome,
)

FIXTURE_MODEL_SHA256 = "270cba1bd5109f42d03350f60406024560464db173c0e387d91f0426d3bd256d"
FIXTURE_PROMPT = "One day, a rabbit ran down the road."
FIXTURE_PROMPT_SHA256 = hashlib.sha256(FIXTURE_PROMPT.encode()).hexdigest()
_COMPLETION = json.dumps({
    "prompt": FIXTURE_PROMPT, "n_predict": 1, "temperature": 0, "cache_prompt": False,
}).encode()
_FIXTURE_PREFILL_TOKENS = 20
_FIXTURE_STARTUP_TOKENS = 2
_MAX_RESPONSE_BYTES = 65_536
_MAX_RECEIPT_BYTES = 256


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
        response = json.loads(await reader.readexactly(length))
        if not isinstance(response, dict):
            raise TypeError("invalid fixture HTTP response")
        return int(status), response
    finally:
        writer.close()
        await writer.wait_closed()


async def _complete_once(path: Path, process: subprocess.Popen[bytes], seconds: float) -> bool:
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
            return False
        try:
            status, result = await _exchange(path, "/completion", _COMPLETION)
            return (
                status == 200 and type(result.get("tokens_predicted")) is int and result["tokens_predicted"] == 1
                and type(result.get("tokens_evaluated")) is int and result["tokens_evaluated"] == _FIXTURE_PREFILL_TOKENS
                and isinstance(result.get("content"), str)
            )
        except (OSError, TypeError, ValueError, RecursionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            return False


def _signal_group(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass


def _finish_process(process: subprocess.Popen[bytes], *, request_completed: bool) -> int:
    if request_completed and process.poll() is None:
        _signal_group(process, signal.SIGTERM)
    try:
        return process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        _signal_group(process, signal.SIGKILL)
        return process.wait(timeout=2)


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("duplicate receipt fields")
    return fields


def _receipt_outcome(fd: int, claim: TokenLaunchClaim, status: int, completed: bool) -> TokenLaunchOutcome:
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
            or type(value["cap"]) is not int or value["cap"] != claim.receipt.attempt.tokens
            or type(value["charged"]) is not int or not 0 <= value["charged"] <= value["cap"]):
        return invalid
    reason, charged = value["reason"], value["charged"]
    if (reason == "shutdown" and status == 0 and completed
            and charged >= _FIXTURE_STARTUP_TOKENS + _FIXTURE_PREFILL_TOKENS):
        return TokenLaunchOutcome(status="completed", exit_status=status, observed_work=charged)
    if reason == "cap_denied" and status == 75 and not completed:
        return TokenLaunchOutcome(status="cap_denied", exit_status=status, observed_work=charged)
    if reason == "unsupported_graph" and status == 75 and not completed:
        return TokenLaunchOutcome(status="unsupported_graph", exit_status=status, observed_work=charged)
    if reason == "server_error" and 1 <= status <= 255 and status not in (74, 75) and not completed:
        return TokenLaunchOutcome(status="server_error", exit_status=status, observed_work=charged)
    return invalid


def _run_claim(claim: TokenLaunchClaim, binary: Path, model: Path, socket_path: Path, seconds: float) -> TokenLaunchOutcome:
    try:
        read_fd, write_fd = os.pipe()
    except OSError:
        return TokenLaunchOutcome(status="launch_failed")
    try:
        try:
            process = subprocess.Popen(
                [str(binary), "--metis-work-budget", str(claim.receipt.attempt.tokens), "--model", str(model),
                 "--socket", str(socket_path), "--metis-receipt-fd", str(write_fd), "--metis-launch-nonce", claim.nonce],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, pass_fds=(write_fd,),
                start_new_session=True, env={"PATH": os.defpath, "LANG": "C", "TMPDIR": str(socket_path.parent)},
            )
        except OSError:
            return TokenLaunchOutcome(status="launch_failed")
        finally:
            os.close(write_fd)

        completed = False
        interrupted: Literal["timeout", "cancelled"] | None = None
        status = None
        try:
            completed = asyncio.run(_complete_once(socket_path, process, seconds))
        except TimeoutError:
            interrupted = "timeout"
        except KeyboardInterrupt:
            interrupted = "cancelled"
        finally:
            if interrupted is not None:
                _signal_group(process, signal.SIGKILL)
            try:
                status = _finish_process(process, request_completed=completed)
            except subprocess.TimeoutExpired:
                pass

        if status is None:
            return TokenLaunchOutcome(status="lost")
        if interrupted is not None:
            return TokenLaunchOutcome(status=interrupted, exit_status=status)
        return _receipt_outcome(read_fd, claim, status, completed)
    finally:
        os.close(read_fd)


def qualify_native_launch(
    admission: StudyTokenAdmission, receipt: TokenAdmissionReceipt, *,
    binary: Path, model: Path, seconds: float = 10,
) -> TokenLaunchOutcome:
    """Run one fixed public fixture request. The admission is never refunded."""
    receipt = TokenAdmissionReceipt.model_validate(receipt)
    if (receipt.study.model_sha256 != FIXTURE_MODEL_SHA256
            or receipt.attempt.prompt_sha256 != FIXTURE_PROMPT_SHA256):
        raise ValueError("only the registered single-file public fixture is supported")
    if not 0 < seconds <= 30:
        raise ValueError("fixture deadline is outside its bound")

    with tempfile.TemporaryDirectory(prefix="metis-native-", dir="/tmp") as folder:
        root = Path(folder).resolve()
        staged_binary, staged_model = root / "server", root / "fixture.gguf"
        _stage(binary, staged_binary, receipt.study.runtime_sha256, limit=128 * 1024**2, executable=True)
        # The digest identifies the entire registered single-file GGUF. Other
        # file layouts, including split GGUFs, cannot reach launch.
        _stage(model, staged_model, FIXTURE_MODEL_SHA256, limit=2 * 1024**2)
        claim = admission.claim_for_launch(receipt)
        outcome = _run_claim(claim, staged_binary, staged_model, root / "server.sock", seconds)
        admission.record_outcome(claim, outcome)
        return outcome
