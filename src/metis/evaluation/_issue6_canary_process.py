"""Fixed stdlib-only guardian and public worker, executed with Python -I -S."""

from __future__ import annotations

import fcntl
import hashlib
import os
import select
import signal
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

_FIXTURE = b"synthetic public fixture: compile, test, package\n"


def _remaining(cutoff: float, wall: float) -> float:
    return min(cutoff - time.monotonic(), wall - time.time())


def _stop(lease: int, parent: int, cutoff: float, wall: float, *, wait: float = 0) -> str | None:
    if os.getppid() != parent:
        return "lease_closed"
    remaining = _remaining(cutoff, wall)
    if remaining <= 0:
        return "deadline"
    ready, _, _ = select.select([lease], [], [], min(wait, remaining))
    if os.getppid() != parent:
        return "lease_closed"
    if ready:
        return "cancelled" if os.read(lease, 1) else "lease_closed"
    return None


def _deny_external(event: str, _args: tuple[object, ...]) -> None:
    if event.startswith(("socket.", "subprocess.", "os.exec", "os.fork", "os.spawn", "os.posix_spawn", "os.system")):
        raise PermissionError("external operations are disabled for the public canary")


def _worker(lease: int, parent: int, scratch: Path, cutoff: float, wall: float, behavior: str) -> int:
    sys.addaudithook(_deny_external)
    remaining = _remaining(cutoff, wall)
    if remaining <= 0:
        return 1
    signal.setitimer(signal.ITIMER_REAL, remaining)
    # The guardian is the only possessor of the writer. EOF before GO means no work.
    if os.read(lease, 1) != b"G" or _stop(lease, parent, cutoff, wall) is not None:
        return 1
    with (scratch / "active").open("xb") as marker:
        fcntl.flock(marker, fcntl.LOCK_EX)
        if behavior == "wait_for_stop":
            while _stop(lease, parent, cutoff, wall, wait=0.02) is None:
                pass
            return 1
        hashlib.sha256(_FIXTURE).digest()
    return 0


def _finish(database: Path, reservation: int, nonce: str, outcome: str) -> None:
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("""UPDATE issue6_canaries SET state='reaped', outcome=?
            WHERE reservation=? AND nonce=? AND state='pending'""", (outcome, reservation, nonce))


def _guardian(lease: int, parent: int, database: Path, reservation: int, nonce: str, scratch: Path,
              cutoff: float, wall: float, behavior: str) -> int:
    # No recovered PID is ever signalled. Only the direct child handle is used.
    with closing(sqlite3.connect(database)) as db:
        record = db.execute("""
            SELECT scratch, state, monotonic_cutoff, wall_cutoff
            FROM issue6_canaries WHERE reservation=? AND nonce=?
        """, (reservation, nonce)).fetchone()
    if record != (scratch.name, "pending", cutoff, wall):
        return 1
    reason = _stop(lease, parent, cutoff, wall)
    if reason is not None:
        _finish(database, reservation, nonce, reason)
        return 0
    scratch.mkdir(mode=0o700)
    reader, writer = os.pipe()
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", __file__, "worker", str(reader), str(os.getpid()), str(scratch),
             str(cutoff), str(wall), behavior],
            env={"PATH": os.defpath, "LANG": "C"}, pass_fds=(reader,), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        reason = _stop(lease, parent, cutoff, wall)
        if reason is None:
            os.write(writer, b"G")
            while (reason := _stop(lease, parent, cutoff, wall, wait=0.02)) is None:
                exit_code = process.poll()
                if exit_code is not None:
                    if _remaining(cutoff, wall) <= 0:
                        reason = "deadline"
                    else:
                        reason = "completed" if exit_code == 0 else "worker_failed"
                    break
    finally:
        os.close(reader)
        os.close(writer)
        if process is not None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=1)
    (scratch / "active").unlink(missing_ok=True)
    scratch.rmdir()
    _finish(database, reservation, nonce, reason)
    return 0


def main() -> int:
    role, *args = sys.argv[1:]
    if role == "guardian":
        lease, parent, database, reservation, nonce, scratch, cutoff, wall, behavior = args
        return _guardian(int(lease), int(parent), Path(database), int(reservation), nonce, Path(scratch),
                         float(cutoff), float(wall), behavior)
    if role == "worker":
        lease, parent, scratch, cutoff, wall, behavior = args
        return _worker(int(lease), int(parent), Path(scratch), float(cutoff), float(wall), behavior)
    raise ValueError("unknown public canary process role")


if __name__ == "__main__":
    sys.exit(main())
