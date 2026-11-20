"""Fixed stdlib-only guardian and public worker, executed with Python -I -S."""

from __future__ import annotations

import fcntl
import hashlib
import os
import select
import signal
import sqlite3
import stat
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import IO

NATIVE_VERSION = "0.169.0"
NATIVE_SIZE = 280_704_736
NATIVE_SHA256 = "739cda86e15d30a6e2b40cf8dcbbfb988aaf48b305b27065573bb8e9fd41d002"
_SANDBOX = "/usr/bin/sandbox-exec"
_OUTPUT_LIMIT = 4096

_FIXTURE = b"synthetic public fixture: compile, test, package\n"


def _remaining(cutoff: float, wall: float) -> float:
    return min(cutoff - time.monotonic(), wall - time.time())


def _stop(lease: int, parent: int, cutoff: float, wall: float, *, wait: float = 0) -> str | None:
    if os.getppid() != parent:
        return "lease_closed"
    remaining = _remaining(cutoff, wall)
    if remaining <= 0:
        return "deadline"
    poller = select.poll()
    poller.register(lease, select.POLLIN | select.POLLHUP | select.POLLERR)
    ready = poller.poll(max(0, int(min(wait, remaining) * 1000)))
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


def stage_native(source: Path, destination: Path, *, size: int, digest: str) -> None:
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    checksum = hashlib.sha256()
    with os.fdopen(os.open(source.resolve(strict=True), flags), "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != size:
            raise RuntimeError("Issue #6 requires the pinned native Codex binary")
        with destination.open("xb") as staged:
            remaining = size
            while remaining:
                block = stream.read(min(remaining, 1024 * 1024))
                if not block:
                    raise RuntimeError("native Codex changed while being staged")
                staged.write(block)
                checksum.update(block)
                remaining -= len(block)
            if stream.read(1) or checksum.hexdigest() != digest:
                raise RuntimeError("Issue #6 requires the pinned native Codex binary")
            os.fchmod(staged.fileno(), 0o500)


def _literal(path: Path) -> str:
    if any(character in str(path) for character in ('"', "\\", "\n", "\r")):
        raise ValueError("invalid runtime sandbox path")
    return f'"{path}"'


def runtime_profile(binary: Path) -> str:
    # No network and no writes, even within scratch. The guardian owns all output.
    return f"""(version 1)
(deny default)
(allow sysctl-read)
(allow file-read* (literal "/") (subpath "/System/Library") (subpath "/usr/lib") (subpath "/private/var/db/dyld"))
(allow file-read* (literal {_literal(binary)}))
(allow process-exec (literal {_literal(binary)}))
(deny process-fork)
(deny network*)
(deny file-write*)
"""


def _sandbox_argv(profile: Path, binary: Path, *args: str) -> list[str]:
    if sys.platform != "darwin" or not os.access(_SANDBOX, os.X_OK):
        raise RuntimeError("offline Codex runtime requires macOS Seatbelt")
    return [_SANDBOX, "-f", str(profile), str(binary), *args]


def _runtime_command(scratch: Path, source: Path) -> list[str]:
    binary = scratch / "pinned-codex"
    profile = scratch / "runtime.sb"
    stage_native(source, binary, size=NATIVE_SIZE, digest=NATIVE_SHA256)
    profile.write_text(runtime_profile(binary), encoding="ascii")
    return _sandbox_argv(profile, binary, "--version")


def _read_stream(stream: IO[bytes] | None, output: bytearray) -> bool:
    # The streams are set nonblocking by the direct guardian immediately after spawn.
    if stream is not None:
        try:
            output.extend(os.read(stream.fileno(), _OUTPUT_LIMIT + 1 - len(output)))
        except BlockingIOError:
            pass
    return len(output) <= _OUTPUT_LIMIT


def _finish(database: Path, reservation: int, nonce: str, outcome: str) -> None:
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("""UPDATE issue6_canaries SET state='reaped', outcome=?
            WHERE reservation=? AND nonce=? AND state='pending'""", (outcome, reservation, nonce))


def _pending(database: Path, reservation: int, nonce: str, scratch: Path,
             cutoff: float, wall: float) -> bool:
    with closing(sqlite3.connect(database)) as db:
        record = db.execute("""
            SELECT scratch, state, monotonic_cutoff, wall_cutoff
            FROM issue6_canaries WHERE reservation=? AND nonce=?
        """, (reservation, nonce)).fetchone()
    return record == (scratch.name, "pending", cutoff, wall)



def _reap(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=1)


def _guardian(lease: int, parent: int, database: Path, reservation: int, nonce: str, scratch: Path,
              cutoff: float, wall: float, behavior: str) -> int:
    # No recovered PID is ever signalled. Only the direct child handle is used.
    if not _pending(database, reservation, nonce, scratch, cutoff, wall):
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
            _reap(process)
    (scratch / "active").unlink(missing_ok=True)
    scratch.rmdir()
    _finish(database, reservation, nonce, reason)
    return 0


def _runtime_guardian(lease: int, parent: int, database: Path, reservation: int, nonce: str, scratch: Path,
                      cutoff: float, wall: float, source: Path) -> int:
    if not _pending(database, reservation, nonce, scratch, cutoff, wall):
        return 1
    reason = _stop(lease, parent, cutoff, wall)
    if reason is not None:
        _finish(database, reservation, nonce, reason)
        return 0

    scratch.mkdir(mode=0o700)
    process = None
    reason = "preflight_failed"
    try:
        command = _runtime_command(scratch, source)
        reason = _stop(lease, parent, cutoff, wall)
        if reason is None:
            process = subprocess.Popen(
                command, cwd="/", env={"PATH": "/usr/bin:/bin", "LANG": "C", "HOME": str(scratch),
                                          "CODEX_HOME": str(scratch), "TMPDIR": str(scratch)},
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
            )
            assert process.stdout is not None and process.stderr is not None
            os.set_blocking(process.stdout.fileno(), False)
            os.set_blocking(process.stderr.fileno(), False)
            stdout, stderr = bytearray(), bytearray()
            while (reason := _stop(lease, parent, cutoff, wall, wait=0.02)) is None:
                status = process.poll()
                if not _read_stream(process.stdout, stdout) or not _read_stream(process.stderr, stderr):
                    reason = "output_limit"
                    break
                if status is not None:
                    expected = f"codex-cli {NATIVE_VERSION}\n".encode("ascii")
                    # The pinned CLI probes PATH aliases before printing --version. The
                    # exact warning confirms Seatbelt denied reading the empty CODEX_HOME.
                    denied_aliases = (
                        "WARNING: proceeding, even though we could not create PATH aliases: "
                        f'failed to read CODEX_HOME "{scratch}": Operation not permitted (os error 1)\n'
                    ).encode("ascii")
                    valid = status == 0 and stdout == expected and stderr in (b"", denied_aliases)
                    reason = "completed" if valid else "invalid_probe"
                    break
    except (OSError, RuntimeError, ValueError):
        reason = "runtime_failed"
    finally:
        if process is not None:
            _reap(process)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
    (scratch / "pinned-codex").unlink(missing_ok=True)
    (scratch / "runtime.sb").unlink(missing_ok=True)
    scratch.rmdir()
    if reason == "completed":
        reason = _stop(lease, parent, cutoff, wall) or reason
    _finish(database, reservation, nonce, reason)
    return 0


def main() -> int:
    role, *args = sys.argv[1:]
    if role == "guardian":
        lease, parent, database, reservation, nonce, scratch, cutoff, wall, behavior = args
        return _guardian(int(lease), int(parent), Path(database), int(reservation), nonce, Path(scratch),
                         float(cutoff), float(wall), behavior)
    if role == "runtime_guardian":
        lease, parent, database, reservation, nonce, scratch, cutoff, wall, source = args
        return _runtime_guardian(int(lease), int(parent), Path(database), int(reservation), nonce,
                                 Path(scratch), float(cutoff), float(wall), Path(source))
    if role == "worker":
        lease, parent, scratch, cutoff, wall, behavior = args
        return _worker(int(lease), int(parent), Path(scratch), float(cutoff), float(wall), behavior)
    raise ValueError("unknown public canary process role")


if __name__ == "__main__":
    sys.exit(main())
