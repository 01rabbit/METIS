import json
from dataclasses import asdict, replace

import pytest

from metis.evaluation.issue6_canary_events import (
    MAX_EVENTS,
    MAX_LINE_BYTES,
    MAX_MESSAGE_BYTES,
    MAX_STDERR_BYTES,
    MAX_STDOUT_BYTES,
    CliUsage,
    Outcome,
    TurnBoundary,
    finalize_canary,
)

THREAD_ID = "01234567-89ab-cdef-0123-456789abcdef"
PRIVATE_REASONING = "sensitive payload must not persist"
ANSWER = b'{"ok":true}'
BOUNDARY = TurnBoundary(exit_code=0, reaped_at=2, scrubbed_at=3, finalized_at=4, deadline=5,
                        last_message_was_fresh=True)
KEY, SCOPE = bytes(range(32)), b"s" * 32
USAGE = {
    "input_tokens": 15, "cached_input_tokens": 3, "cache_write_input_tokens": 2,
    "output_tokens": 8, "reasoning_output_tokens": 4,
}
THREAD = {"type": "thread.started", "thread_id": THREAD_ID}
START = {"type": "turn.started"}
REASONING = {"type": "item.completed", "item": {"type": "reasoning", "id": "item_0", "text": PRIVATE_REASONING}}
MESSAGE = {"type": "item.completed", "item": {"type": "agent_message", "id": "item_1", "text": ANSWER.decode()}}
TERMINAL = {"type": "turn.completed", "usage": USAGE}


def jsonl(*events):
    return b"".join(json.dumps(event, separators=(",", ":")).encode() + b"\n" for event in events)


def good():
    return jsonl(THREAD, START, REASONING, MESSAGE, TERMINAL)


def finalize(stdout=None, stderr=b"", last_message=ANSWER, boundary=BOUNDARY, scope=SCOPE):
    if stdout is None:
        stdout = good()
    return finalize_canary(stdout, stderr, last_message, boundary, commitment_key=KEY, reservation_scope=scope)


def test_valid_turn_projects_only_cli_usage_and_scoped_commitments():
    receipt = finalize()
    assert receipt.outcome == Outcome.COMPLETED
    assert receipt.cli_usage == CliUsage(15, 3, 2, 8, 4)
    assert receipt == finalize()
    assert receipt.thread_hmac != receipt.response_hmac
    assert receipt.thread_hmac != finalize(scope=b"q" * 32).thread_hmac
    serialized = json.dumps(asdict(receipt))
    assert PRIVATE_REASONING not in serialized and THREAD_ID not in serialized and ANSWER.decode() not in serialized


@pytest.mark.parametrize(("trace", "outcome"), [
    (b"", Outcome.MISSING_TERMINAL),
    (good()[:-1], Outcome.MALFORMED),
    (good().replace(b"\n", b"\r\n"), Outcome.MALFORMED),
    (b"\xff\n", Outcome.MALFORMED),
    (b"\n" + good(), Outcome.MALFORMED),
    (b'{"type":"thread.started","type":"turn.started"}\n', Outcome.MALFORMED),
    (b'{"type":"thread.started","thread_id":"\\ud801"}\n', Outcome.UNEXPECTED_EVENT),
    (b'{"type":[' + b"[" * 2000 + b"]" * 2001 + b"}\n", Outcome.MALFORMED),
    (b'{"type":"error","message":NaN}\n', Outcome.MALFORMED),
    (jsonl(THREAD, START, MESSAGE), Outcome.MISSING_TERMINAL),
    (jsonl(THREAD, START, TERMINAL), Outcome.UNEXPECTED_EVENT),
    (jsonl(THREAD, THREAD, START, MESSAGE, TERMINAL), Outcome.UNEXPECTED_EVENT),
    (jsonl(THREAD, START, START, MESSAGE, TERMINAL), Outcome.UNEXPECTED_EVENT),
    (jsonl(THREAD, START, MESSAGE, MESSAGE, TERMINAL), Outcome.UNEXPECTED_EVENT),
    (jsonl(THREAD, START, REASONING, REASONING, MESSAGE, TERMINAL), Outcome.UNEXPECTED_EVENT),
    (jsonl(THREAD, START, MESSAGE, TERMINAL, TERMINAL), Outcome.UNEXPECTED_EVENT),
    (jsonl(THREAD, START, MESSAGE, TERMINAL, {"type": "turn.started"}), Outcome.UNEXPECTED_EVENT),
    (jsonl(THREAD, START, {"type": "model.retry"}, MESSAGE, TERMINAL), Outcome.UNEXPECTED_EVENT),
    (jsonl(THREAD, START, {"type": "error", "message": PRIVATE_REASONING}, MESSAGE, TERMINAL),
     Outcome.REPORTED_ERROR),
    (jsonl(THREAD, START, {"type": "turn.failed", "error": {"message": PRIVATE_REASONING}}),
     Outcome.REPORTED_ERROR),
])
def test_malformed_missing_or_ambiguous_transcript_has_no_usage_or_commitments(trace, outcome):
    receipt = finalize(trace)
    assert receipt.outcome == outcome
    assert receipt.cli_usage is receipt.thread_hmac is receipt.response_hmac is None


@pytest.mark.parametrize("category", [
    "command_execution", "file_change", "mcp_tool_call", "collab_tool_call", "web_search", "todo_list", "future_tool",
])
@pytest.mark.parametrize("event", ["item.started", "item.updated", "item.completed"])
def test_tool_or_unknown_item_is_rejected_at_any_lifecycle_stage(event, category):
    item = {"type": event, "item": {"id": "item_4", "type": category, "secret": PRIVATE_REASONING}}
    receipt = finalize(jsonl(THREAD, START, item, MESSAGE, TERMINAL))
    assert receipt.outcome == Outcome.TOOL_POLICY
    assert PRIVATE_REASONING not in repr(receipt)


def test_error_item_and_stderr_do_not_qualify_even_with_successful_turn():
    warning = {"type": "item.completed", "item": {"id": "item_2", "type": "error", "message": "model rerouted"}}
    assert finalize(jsonl(THREAD, START, warning, MESSAGE, TERMINAL)).outcome == Outcome.REPORTED_ERROR
    assert finalize(stderr=b"tools::router denied").outcome == Outcome.TOOL_POLICY
    assert finalize(stderr=b"reconnecting stream").outcome == Outcome.REPORTED_ERROR


@pytest.mark.parametrize("changes", [
    {"input_tokens": True},
    {"input_tokens": 0},
    {"output_tokens": 0},
    {"cache_write_input_tokens": -1},
    {"cache_write_input_tokens": 2**63},
    {"cached_input_tokens": 16},
    {"reasoning_output_tokens": 9},
    {"unknown_counter": 1},
])
def test_invalid_usage_cannot_qualify(changes):
    event = {"type": "turn.completed", "usage": {**USAGE, **changes}}
    assert finalize(jsonl(THREAD, START, MESSAGE, event)).outcome == Outcome.INVALID_USAGE


def test_zero_renderer_defaults_and_missing_usage_are_not_measurements():
    zero = {"type": "turn.completed", "usage": dict.fromkeys(USAGE, 0)}
    missing = {"type": "turn.completed", "usage": {k: v for k, v in USAGE.items() if k != "cache_write_input_tokens"}}
    assert finalize(jsonl(THREAD, START, MESSAGE, zero)).outcome == Outcome.INVALID_USAGE
    assert finalize(jsonl(THREAD, START, MESSAGE, missing)).outcome == Outcome.INVALID_USAGE


@pytest.mark.parametrize(("updates", "expected"), [
    ({"exit_code": 2}, Outcome.RUNTIME_FAILURE),
    ({"exit_code": False}, Outcome.RUNTIME_FAILURE),
    ({"reaped_at": None}, Outcome.UNCERTAIN_CLEANUP),
    ({"scrubbed_at": None}, Outcome.UNCERTAIN_CLEANUP),
    ({"scrubbed_at": 1}, Outcome.UNCERTAIN_CLEANUP),
    ({"finalized_at": float("inf")}, Outcome.UNCERTAIN_CLEANUP),
    ({"reaped_at": float("nan")}, Outcome.UNCERTAIN_CLEANUP),
    ({"deadline": -1}, Outcome.UNCERTAIN_CLEANUP),
    ({"reaped_at": True}, Outcome.UNCERTAIN_CLEANUP),
    ({"scrubbed_at": "3"}, Outcome.UNCERTAIN_CLEANUP),
    ({"finalized_at": 10**400}, Outcome.UNCERTAIN_CLEANUP),
    ({"deadline": "5"}, Outcome.UNCERTAIN_CLEANUP),
    ({"cancelled": "false"}, Outcome.UNCERTAIN_CLEANUP),
    ({"cancelled": 0}, Outcome.UNCERTAIN_CLEANUP),
    ({"finalized_at": 5}, Outcome.DEADLINE),
    ({"cancelled": True}, Outcome.CANCELLED),
    ({"last_message_was_fresh": False}, Outcome.INVALID_RESPONSE),
    ({"last_message_was_fresh": 1}, Outcome.INVALID_RESPONSE),
])
def test_requires_bounded_reaped_scrubbed_success(updates, expected):
    receipt = finalize(boundary=replace(BOUNDARY, **updates))
    assert receipt.outcome == expected
    assert receipt.cli_usage is None


@pytest.mark.parametrize("content", [b"", b'{"ok": true}', ANSWER + b"\n"])
def test_last_message_must_match_exact_agent_bytes(content):
    assert finalize(last_message=content).outcome == Outcome.INVALID_RESPONSE


@pytest.mark.parametrize("answer", [b'{"ok":false}', b'{"ok":1}', b'{"ok":true,"extra":true}'])
def test_exact_public_response_schema(answer):
    message = {"type": "item.completed", "item": {**MESSAGE["item"], "text": answer.decode()}}
    assert finalize(jsonl(THREAD, START, message, TERMINAL), last_message=answer).outcome == Outcome.INVALID_RESPONSE


def test_source_limits_apply_before_retaining_evidence():
    assert finalize(b"x" * (MAX_STDOUT_BYTES + 1)).outcome == Outcome.CAPTURE_LIMIT
    assert finalize((b"x" * (MAX_LINE_BYTES + 1)) + b"\n").outcome == Outcome.CAPTURE_LIMIT
    assert finalize(b"\n" * (MAX_EVENTS + 1)).outcome == Outcome.CAPTURE_LIMIT
    assert finalize(stderr=b"x" * (MAX_STDERR_BYTES + 1)).outcome == Outcome.CAPTURE_LIMIT
    assert finalize(last_message=b"x" * (MAX_MESSAGE_BYTES + 1)).outcome == Outcome.CAPTURE_LIMIT



def test_captures_must_be_exact_bytes():
    assert finalize(good().decode()).outcome == Outcome.MALFORMED
    assert finalize(stderr="").outcome == Outcome.MALFORMED
    assert finalize(last_message=bytearray(ANSWER)).outcome == Outcome.MALFORMED
