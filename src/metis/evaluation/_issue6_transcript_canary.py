"""A guardian-owned public JSONL stub, with no runtime executable input."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import signal
import sqlite3
import stat
import subprocess
import sys
import time
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import IO, Literal

from ._issue6_canary_process import _deny_external, _pending, _reap, _remaining, _stop
from .issue6_canary_events import (
    MAX_MESSAGE_BYTES,
    MAX_STDERR_BYTES,
    MAX_STDOUT_BYTES,
    CanaryEvidence,
    Outcome,
    TurnBoundary,
    finalize_canary,
)

StubMode = Literal["complete", "tool", "wrong_file", "stdout_overflow", "stderr_overflow",
                   "last_overflow", "hold", "nonzero"]
STUB_MODES = {"complete", "tool", "wrong_file", "stdout_overflow", "stderr_overflow",
              "last_overflow", "hold", "nonzero"}
_TRANSCRIPT_TABLE = """CREATE TABLE IF NOT EXISTS issue6_canary_transcripts (
    reservation INTEGER PRIMARY KEY, evidence TEXT NOT NULL
)"""
_HELPER = Path(__file__).with_name("_issue6_canary_process.py")
_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C"}
_THREAD = "01234567-89ab-cdef-0123-456789abcdef"
_ANSWER = b'{"ok":true}'
_PUBLIC_TRACE = (
    {"type": "thread.started", "thread_id": _THREAD},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"type": "agent_message", "id": "item_0", "text": _ANSWER.decode()}},
    {"type": "turn.completed", "usage": {
        "input_tokens": 3, "cached_input_tokens": 0, "cache_write_input_tokens": 0,
        "output_tokens": 2, "reasoning_output_tokens": 0,
    }},
)


def _fresh_last_message(path: Path) -> int:
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    entry = os.fstat(descriptor)
    if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1 or entry.st_size != 0:
        os.close(descriptor)
        raise RuntimeError("last-message output did not start as an exclusive empty regular file")
    return descriptor


def _stub(lease: int, last: int, parent: int, cutoff: float, wall: float, mode: str) -> int:
    sys.addaudithook(_deny_external)
    remaining = _remaining(cutoff, wall)
    if mode not in STUB_MODES or remaining <= 0:
        return 1
    signal.setitimer(signal.ITIMER_REAL, remaining)
    if os.read(lease, 1) != b"G" or _stop(lease, parent, cutoff, wall) is not None:
        return 1
    fcntl.flock(last, fcntl.LOCK_EX)
    if mode == "hold":
        while _stop(lease, parent, cutoff, wall, wait=0.02) is None:
            pass
        return 1
    if mode == "stdout_overflow":
        sys.stdout.buffer.write(b"x" * (MAX_STDOUT_BYTES + 1))
        return 0
    if mode == "stderr_overflow":
        sys.stderr.buffer.write(b"x" * (MAX_STDERR_BYTES + 1))
        return 0
    if mode == "last_overflow":
        os.write(last, b"x" * (MAX_MESSAGE_BYTES + 1))
    elif mode == "wrong_file":
        os.write(last, b'{"ok":false}')
    else:
        os.write(last, _ANSWER)
    for event in _PUBLIC_TRACE:
        if mode == "tool" and event["type"] == "item.completed":
            event = {"type": "item.started", "item": {"type": "mcp_tool_call", "id": "item_0"}}
        print(json.dumps(event, separators=(",", ":")))
    return 1 if mode == "nonzero" else 0


def _drain(stream: IO[bytes], buffer: bytearray, limit: int) -> bool:
    # Preserve the first byte over the cap and drain already buffered chunks to EOF/EAGAIN.
    while len(buffer) <= limit:
        try:
            chunk = os.read(stream.fileno(), min(4096, limit + 1 - len(buffer)))
        except BlockingIOError:
            return True
        if not chunk:
            return True
        buffer.extend(chunk)
    return False


def _finish(database: Path, reservation: int, nonce: str, evidence: CanaryEvidence,
            cutoff: float, wall: float, lease: int, parent: int) -> None:
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if evidence.outcome == Outcome.COMPLETED:
            stop = _stop(lease, parent, cutoff, wall)
            if stop is not None:
                evidence = CanaryEvidence(Outcome.DEADLINE if stop == "deadline" else Outcome.CANCELLED)
        changed = db.execute("""
            UPDATE issue6_canaries SET state='reaped', outcome=?
            WHERE reservation=? AND nonce=? AND state='pending'
        """, (evidence.outcome, reservation, nonce))
        if changed.rowcount != 1:
            raise RuntimeError("transcript canary terminal reservation was no longer pending")
        db.execute(_TRANSCRIPT_TABLE)
        payload = json.dumps(asdict(evidence), sort_keys=True, separators=(",", ":"))
        db.execute("INSERT INTO issue6_canary_transcripts VALUES (?, ?)", (reservation, payload))
        joined = db.execute("""
            SELECT c.state, c.outcome, t.evidence
            FROM issue6_canaries c JOIN issue6_canary_transcripts t ON t.reservation=c.reservation
            WHERE c.reservation=? AND c.nonce=?
        """, (reservation, nonce)).fetchone()
        if joined != ("reaped", evidence.outcome, payload):
            raise RuntimeError("transcript canary terminal evidence does not match reservation")


def _guardian(lease: int, parent: int, database: Path, reservation: int, nonce: str, scratch: Path,
              cutoff: float, wall: float, mode: str) -> int:
    if mode not in STUB_MODES or not _pending(database, reservation, nonce, scratch, cutoff, wall):
        return 1
    reason = _stop(lease, parent, cutoff, wall)
    if reason is not None:
        # No child exists to reap; still close the charged reservation explicitly.
        _finish(database, reservation, nonce, CanaryEvidence(
            Outcome.DEADLINE if reason == "deadline" else Outcome.CANCELLED,
        ), cutoff, wall, lease, parent)
        return 0
    scratch.mkdir(mode=0o700)
    last_path = scratch / "last.json"
    last = _fresh_last_message(last_path)
    stdout, stderr = bytearray(), bytearray()
    try:
        reader, writer = os.pipe()
        try:
            process = subprocess.Popen(
                [sys.executable, "-I", "-S", str(_HELPER), "transcript_stub", str(reader), str(last),
                 str(os.getpid()), str(cutoff), str(wall), mode],
                env=_ENV, cwd=scratch, pass_fds=(reader, last), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
            )
            assert process.stdout is not None and process.stderr is not None
            try:
                os.set_blocking(process.stdout.fileno(), False)
                os.set_blocking(process.stderr.fileno(), False)
                reason = _stop(lease, parent, cutoff, wall)
                if reason is None:
                    os.write(writer, b"G")
                    while (reason := _stop(lease, parent, cutoff, wall, wait=0.02)) is None:
                        status = process.poll()
                        fits_stdout = _drain(process.stdout, stdout, MAX_STDOUT_BYTES)
                        fits_stderr = _drain(process.stderr, stderr, MAX_STDERR_BYTES)
                        if not fits_stdout or not fits_stderr or status is not None:
                            break
            finally:
                _reap(process)
                reaped = time.monotonic()
                process.stdout.close()
                process.stderr.close()
        finally:
            os.close(reader)
            os.close(writer)
        identity = os.fstat(last)
        by_name = last_path.lstat()
        if (identity.st_dev, identity.st_ino, identity.st_nlink) != (by_name.st_dev, by_name.st_ino, 1):
            raise RuntimeError("last-message file identity changed")
        os.lseek(last, 0, os.SEEK_SET)
        last_message = os.read(last, MAX_MESSAGE_BYTES + 1)
    finally:
        os.close(last)
    last_path.unlink()
    scratch.rmdir()
    scrubbed = time.monotonic()
    reason = _stop(lease, parent, cutoff, wall) or reason
    finalizing = time.monotonic()
    boundary = TurnBoundary(
        exit_code=process.returncode, reaped_at=reaped, scrubbed_at=scrubbed, finalized_at=finalizing,
        deadline=finalizing if reason == "deadline" else cutoff, last_message_was_fresh=True,
        cancelled=reason in {"cancelled", "lease_closed"},
    )
    # The per-run key is intentionally discarded: these HMACs redact raw values, but
    # they are not later-verifiable commitments and must not be treated as such.
    evidence = finalize_canary(bytes(stdout), bytes(stderr), last_message, boundary,
                              commitment_key=secrets.token_bytes(32), reservation_scope=hashlib.sha256(
                                  bytes.fromhex(nonce)).digest())
    _finish(database, reservation, nonce, evidence, cutoff, wall, lease, parent)
    return 0


def dispatch(role: str, args: list[str]) -> int:
    if role == "transcript_guardian":
        lease, parent, database, reservation, nonce, scratch, cutoff, wall, mode = args
        return _guardian(int(lease), int(parent), Path(database), int(reservation), nonce,
                         Path(scratch), float(cutoff), float(wall), mode)
    if role == "transcript_stub":
        lease, last, parent, cutoff, wall, mode = args
        return _stub(int(lease), int(last), int(parent), float(cutoff), float(wall), mode)
    raise ValueError("unknown transcript canary process role")
