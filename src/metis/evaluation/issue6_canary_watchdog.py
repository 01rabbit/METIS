"""Controller for one approved, fixed public fixture under a disposable watchdog."""

from __future__ import annotations

import math
import os
import secrets
import sqlite3
import stat
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Literal, Self

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

    def __init__(self, process: subprocess.Popen[bytes], lease: int):
        self._process = process
        self._lease = lease

    @property
    def guardian_pid(self) -> int:
        return self._process.pid

    def cancel(self) -> None:
        if self._lease >= 0:
            lease, self._lease = self._lease, -1
            try:
                os.write(lease, b"C")
            except (BlockingIOError, BrokenPipeError):
                # A queued signal already wakes the guardian, or the guardian exited.
                pass
            finally:
                os.close(lease)

    def wait(self, *, timeout: float = 8) -> int:
        try:
            return self._process.wait(timeout=timeout)
        finally:
            self.cancel()

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
    if behavior not in {"complete", "wait_for_stop"} or not math.isfinite(seconds) or not 0 < seconds <= _MAX_SECONDS:
        raise ValueError("unsupported canary behavior or deadline")
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
    reader, writer = os.pipe()
    try:
        os.set_blocking(writer, False)
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", str(_HELPER), "guardian", str(reader), str(os.getpid()),
             str(window.database),
             str(reservation), nonce, str(scratch), str(cutoff), str(window.wall_cutoff), behavior],
            env=_ENV, pass_fds=(reader,), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except BaseException:
        os.close(writer)
        raise
    finally:
        os.close(reader)
    return Canary(process, writer)


def quarantine_expired(database: Path) -> int:
    """Mark expired records with no reap/cleanup proof; leave their scratch alone."""
    with closing(sqlite3.connect(database)) as db, db:
        changed = db.execute("""
            UPDATE issue6_canaries SET state='quarantined', outcome='unconfirmed'
            WHERE state='pending' AND (monotonic_cutoff <= ? OR wall_cutoff <= ?)
        """, (time.monotonic(), time.time()))
        return changed.rowcount
