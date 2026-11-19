"""Controller for one approved, fixed public fixture under a disposable watchdog."""

from __future__ import annotations

import math
import os
import secrets
import socket
import sqlite3
import stat
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Literal, Self

from metis.core.codex_isolation import native_codex

from .issue6_pilot_admission import DryRunAdmission, DryRunPhase

_HELPER = Path(__file__).with_name("_issue6_canary_process.py")
_ENV = {"PATH": os.defpath, "LANG": "C"}
_MAX_SECONDS = 5
_CANARY_TABLE = """CREATE TABLE IF NOT EXISTS issue6_canaries (
            reservation INTEGER PRIMARY KEY, nonce TEXT NOT NULL UNIQUE, scratch TEXT NOT NULL,
            state TEXT NOT NULL, outcome TEXT, wall_cutoff REAL NOT NULL,
            monotonic_cutoff REAL NOT NULL
        )"""


class Canary:
    """Controller lease with an explicit stop signal and EOF on abandonment."""

    def __init__(self, process: subprocess.Popen[bytes], lease: socket.socket):
        self._process = process
        self._lease = lease

    @property
    def guardian_pid(self) -> int:
        return self._process.pid

    def cancel(self) -> None:
        if self._lease.fileno() >= 0:
            try:
                self._lease.send(b"C", socket.MSG_NOSIGNAL)
            except (BlockingIOError, BrokenPipeError, ConnectionResetError):
                # The guardian will read a queued signal, or its connection is gone.
                pass
            finally:
                self._lease.close()

    def wait(self, *, timeout: float = 8) -> int:
        try:
            status = self._process.wait(timeout=timeout)
        except BaseException:
            self.cancel()
            raise
        self._lease.close()
        return status

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_errors: object) -> None:
        self.cancel()
        self.wait()


def start_canary(admission: DryRunAdmission, workspace: Path, run_id: str, assignment_id: str,
                 attempt_id: str, receipt: DryRunPhase, *,
                 behavior: Literal["complete", "wait_for_stop"] = "complete",
                 seconds: float = _MAX_SECONDS) -> Canary:
    """Atomically charge the phase and record intent before starting the fixed worker."""
    if behavior not in {"complete", "wait_for_stop"}:
        raise ValueError("unsupported fixed worker behavior")
    return _start_guardian(admission, workspace, run_id, assignment_id, attempt_id, receipt,
                           "guardian", behavior, seconds)


def start_offline_runtime_canary(admission: DryRunAdmission, workspace: Path, run_id: str, assignment_id: str,
                                 attempt_id: str, receipt: DryRunPhase, executable: Path, *,
                                 seconds: float = _MAX_SECONDS) -> Canary:
    """Run a pin-verified Codex --version command with all network and file writes denied."""
    if sys.platform != "darwin" or not os.access("/usr/bin/sandbox-exec", os.X_OK):
        raise RuntimeError("offline Codex runtime requires macOS Seatbelt")
    source, _ = native_codex(str(executable))
    return _start_guardian(admission, workspace, run_id, assignment_id, attempt_id, receipt,
                           "runtime_guardian", source, seconds)


def _start_guardian(admission: DryRunAdmission, workspace: Path, run_id: str, assignment_id: str,
                    attempt_id: str, receipt: DryRunPhase, role: Literal["guardian", "runtime_guardian"],
                    argument: str, seconds: float) -> Canary:
    if not math.isfinite(seconds) or not 0 < seconds <= _MAX_SECONDS:
        raise ValueError("unsupported canary deadline")
    workspace = workspace.resolve(strict=True)
    info = workspace.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("canary requires a private operator-owned workspace")
    window = admission.canary_window(workspace, receipt)
    cutoff = min(window.monotonic_cutoff, time.monotonic() + seconds)
    if time.monotonic() >= cutoff or time.time() >= window.wall_cutoff:
        raise ValueError("canary deadline reached before reservation")
    nonce = secrets.token_hex(16)
    scratch = workspace / ("canary-" + nonce)

    def persist_pending(db: sqlite3.Connection, reservation: int) -> None:
        db.execute(_CANARY_TABLE)
        db.execute("INSERT INTO issue6_canaries VALUES (?, ?, ?, 'pending', NULL, ?, ?)",
                   (reservation, nonce, scratch.name, window.wall_cutoff, cutoff))

    reservation = admission.reserve_phase(run_id, assignment_id, attempt_id, receipt, persist_pending=persist_pending)
    reader, writer = socket.socketpair()
    try:
        writer.setblocking(False)
        reader_fd = reader.fileno()
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", str(_HELPER), role, str(reader_fd), str(os.getpid()),
             str(window.database),
             str(reservation), nonce, str(scratch), str(cutoff), str(window.wall_cutoff), argument],
            env=_ENV, pass_fds=(reader_fd,), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except BaseException:
        writer.close()
        raise
    finally:
        reader.close()
    return Canary(process, writer)


def quarantine_expired(database: Path) -> int:
    """Mark expired records with no reap/cleanup proof; leave their scratch alone."""
    with closing(sqlite3.connect(database)) as db, db:
        changed = db.execute("""
            UPDATE issue6_canaries SET state='quarantined', outcome='unconfirmed'
            WHERE state='pending' AND (monotonic_cutoff <= ? OR wall_cutoff <= ?)
        """, (time.monotonic(), time.time()))
        return changed.rowcount
