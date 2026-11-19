"""Offline, fail-closed evidence projection for Codex 0.169.0 exec --json.

The caller uses MAX+1 capture on each stream and last-message file, never
truncates an overflow to MAX, and supplies verified process/cleanup observations.
Every launched reservation stays charged, whichever outcome this function returns.
Launch-side tool restrictions and isolation must be checked independently. The
pinned renderer can omit tool/cooperation notifications and cannot attest account
identity, provider request count or absence of retries.
"""

from __future__ import annotations

import hmac
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Never

MAX_STDOUT_BYTES = 128 * 1024
MAX_STDERR_BYTES = 4096
MAX_LINE_BYTES = 8 * 1024
MAX_MESSAGE_BYTES = 1024
MAX_EVENTS = 256
_MAX_JSON_DEPTH = 8
_I64_MAX = 2**63 - 1
_MAX_TIMESTAMP = 2**53 - 1
_THREAD_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
_ITEM_ID = re.compile(r"item_[0-9]{1,10}")


class Outcome(StrEnum):
    COMPLETED = "completed"
    CAPTURE_LIMIT = "capture_limit"
    MALFORMED = "malformed"
    UNEXPECTED_EVENT = "unexpected_event"
    TOOL_POLICY = "tool_policy"
    REPORTED_ERROR = "reported_error"
    MISSING_TERMINAL = "missing_terminal"
    INVALID_USAGE = "invalid_usage"
    INVALID_RESPONSE = "invalid_response"
    RUNTIME_FAILURE = "runtime_failure"
    UNCERTAIN_CLEANUP = "uncertain_cleanup"
    DEADLINE = "deadline"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class CliUsage:
    """Counts from the last cumulative thread-usage notification rendered by CLI."""

    input_tokens: int
    cached_input_tokens: int
    cache_write_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int


@dataclass(frozen=True)
class TurnBoundary:
    """Verified caller observations on one monotonic clock and fresh output file."""

    exit_code: int | None
    reaped_at: float | None
    scrubbed_at: float | None
    finalized_at: float
    deadline: float
    # The controller must create an exclusive empty file in this turn's private workspace.
    last_message_was_fresh: bool
    cancelled: bool = False


@dataclass(frozen=True)
class CanaryEvidence:
    outcome: Outcome
    cli_usage: CliUsage | None = None
    thread_hmac: str | None = None
    response_hmac: str | None = None


class _Rejected(Exception):
    def __init__(self, outcome: Outcome):
        self.outcome = outcome
        super().__init__(outcome.value)


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _integer(value: str) -> int:
    if len(value) > 20:
        raise ValueError("JSON integer exceeds this wire format")
    return int(value)


def _invalid_number(_: str) -> Never:
    raise ValueError("JSON number is outside this wire format")


def _object(data: bytes) -> dict[str, object]:
    depth = 0
    quoted = False
    escaped = False
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:  # backslash
                escaped = True
            elif byte == 34:  # quotation mark
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in b"{[":
            depth += 1
            if depth > _MAX_JSON_DEPTH:
                raise _Rejected(Outcome.MALFORMED)
        elif byte in b"}]":
            depth -= 1
    value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_int=_integer,
                       parse_float=_invalid_number, parse_constant=_invalid_number)
    if not isinstance(value, dict):
        raise _Rejected(Outcome.MALFORMED)
    return value


def _usage(value: object) -> CliUsage:
    if not isinstance(value, dict) or set(value) != set(CliUsage.__dataclass_fields__):
        raise _Rejected(Outcome.INVALID_USAGE)
    if any(type(count) is not int or not 0 <= count <= _I64_MAX for count in value.values()):
        raise _Rejected(Outcome.INVALID_USAGE)
    current = CliUsage(**value)
    # The pinned renderer emits zeroes when no token notification was received.
    if (not current.input_tokens or not current.output_tokens
            or current.cached_input_tokens > current.input_tokens
            or current.reasoning_output_tokens > current.output_tokens):
        raise _Rejected(Outcome.INVALID_USAGE)
    return current


def _parse(stdout: bytes) -> tuple[str, bytes, CliUsage]:
    if not stdout or not stdout.endswith(b"\n"):
        raise _Rejected(Outcome.MISSING_TERMINAL if not stdout else Outcome.MALFORMED)
    if stdout.count(b"\n") > MAX_EVENTS:
        raise _Rejected(Outcome.CAPTURE_LIMIT)
    thread = None
    turn = False
    usage = None
    answer = None
    seen: set[str] = set()
    for line in stdout[:-1].split(b"\n"):
        if len(line) > MAX_LINE_BYTES:
            raise _Rejected(Outcome.CAPTURE_LIMIT)
        if usage is not None:
            raise _Rejected(Outcome.UNEXPECTED_EVENT)
        if not line or line.endswith(b"\r"):
            raise _Rejected(Outcome.MALFORMED)
        event = _object(line)
        kind = event.get("type")
        if kind in ("error", "turn.failed"):
            raise _Rejected(Outcome.REPORTED_ERROR)
        if kind == "thread.started":
            ident = event.get("thread_id")
            if (thread is not None or set(event) != {"type", "thread_id"}
                    or not isinstance(ident, str) or not _THREAD_ID.fullmatch(ident)):
                raise _Rejected(Outcome.UNEXPECTED_EVENT)
            thread = ident
        elif kind == "turn.started":
            if thread is None or turn or set(event) != {"type"}:
                raise _Rejected(Outcome.UNEXPECTED_EVENT)
            turn = True
        elif kind == "turn.completed":
            if not turn or set(event) != {"type", "usage"} or answer is None:
                raise _Rejected(Outcome.UNEXPECTED_EVENT)
            usage = _usage(event["usage"])
        elif kind in ("item.started", "item.updated", "item.completed"):
            item = event.get("item")
            if not isinstance(item, dict):
                raise _Rejected(Outcome.MALFORMED)
            category = item.get("type")
            if category == "error":
                # This covers configuration warnings and model reroutes.
                raise _Rejected(Outcome.REPORTED_ERROR)
            if category not in ("reasoning", "agent_message"):
                raise _Rejected(Outcome.TOOL_POLICY)
            ident, body = item.get("id"), item.get("text")
            if (not turn or kind != "item.completed" or answer is not None or set(event) != {"type", "item"}
                    or set(item) != {"id", "type", "text"} or not isinstance(body, str)
                    or not isinstance(ident, str) or not _ITEM_ID.fullmatch(ident) or ident in seen):
                raise _Rejected(Outcome.UNEXPECTED_EVENT)
            seen.add(ident)
            encoded = body.encode("utf-8")
            if category == "agent_message":
                if len(encoded) > MAX_MESSAGE_BYTES:
                    raise _Rejected(Outcome.CAPTURE_LIMIT)
                answer = encoded
        else:
            raise _Rejected(Outcome.UNEXPECTED_EVENT)
    if thread is None or answer is None or usage is None:
        raise _Rejected(Outcome.MISSING_TERMINAL)
    return thread, answer, usage


def _valid_timestamp(value: object) -> bool:
    if type(value) is not int and type(value) is not float:
        return False
    return 0 <= value <= _MAX_TIMESTAMP


def finalize_canary(stdout: bytes, stderr: bytes, last_message: bytes, boundary: TurnBoundary, *,
                    commitment_key: bytes, reservation_scope: bytes) -> CanaryEvidence:
    """Recognize only a single successful public canary response and emit sanitized evidence."""
    if (type(commitment_key) is not bytes or type(reservation_scope) is not bytes
            or len(commitment_key) != 32 or len(reservation_scope) != 32):
        raise ValueError("commitment key and opaque reservation scope must each be 32 bytes")
    reaped = boundary.reaped_at
    scrubbed = boundary.scrubbed_at
    if reaped is None or scrubbed is None:
        return CanaryEvidence(Outcome.UNCERTAIN_CLEANUP)
    if (type(boundary.cancelled) is not bool or not all(
        _valid_timestamp(stamp) for stamp in (reaped, scrubbed, boundary.finalized_at, boundary.deadline)
    ) or not reaped <= scrubbed <= boundary.finalized_at):
        return CanaryEvidence(Outcome.UNCERTAIN_CLEANUP)
    if boundary.finalized_at >= boundary.deadline:
        return CanaryEvidence(Outcome.DEADLINE)
    if boundary.cancelled:
        return CanaryEvidence(Outcome.CANCELLED)
    if boundary.last_message_was_fresh is not True:
        return CanaryEvidence(Outcome.INVALID_RESPONSE)
    if any(type(stream) is not bytes for stream in (stdout, stderr, last_message)):
        return CanaryEvidence(Outcome.MALFORMED)
    if (len(stdout) > MAX_STDOUT_BYTES or len(stderr) > MAX_STDERR_BYTES
            or len(last_message) > MAX_MESSAGE_BYTES):
        return CanaryEvidence(Outcome.CAPTURE_LIMIT)
    if b"tools::router" in stderr:
        return CanaryEvidence(Outcome.TOOL_POLICY)
    if stderr:
        return CanaryEvidence(Outcome.REPORTED_ERROR)
    if type(boundary.exit_code) is not int or boundary.exit_code != 0:
        return CanaryEvidence(Outcome.RUNTIME_FAILURE)
    try:
        thread, answer, current_usage = _parse(stdout)
        value = _object(answer)
        if answer != last_message or set(value) != {"ok"} or value["ok"] is not True:
            return CanaryEvidence(Outcome.INVALID_RESPONSE)
    except _Rejected as rejection:
        return CanaryEvidence(rejection.outcome)
    except (ValueError, RecursionError):
        return CanaryEvidence(Outcome.MALFORMED)

    def commit(domain: bytes, value: bytes) -> str:
        message = b"metis-issue6-public-canary-v1\x00" + domain + b"\x00" + reservation_scope + value
        return hmac.digest(commitment_key, message, "sha256").hex()

    return CanaryEvidence(Outcome.COMPLETED, current_usage, commit(b"thread", thread.encode("ascii")),
                          commit(b"response", answer))
