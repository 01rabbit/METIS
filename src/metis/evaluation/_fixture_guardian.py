"""Own one trusted native fixture process and monitor the controller pipe."""

from __future__ import annotations

import os
import select
import signal
import subprocess
import sys
import time

TERM_GRACE = 0.5
REAP_TIMEOUT = 2.0
_MAX_OWNER_SECONDS = 35.0


def _stop(worker: subprocess.Popen[bytes], *, force: bool) -> int:
    if not force and worker.poll() is None:
        try:
            os.killpg(worker.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            return worker.wait(timeout=TERM_GRACE)
        except subprocess.TimeoutExpired:
            pass
    if worker.poll() is None:
        try:
            os.killpg(worker.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return worker.wait(timeout=REAP_TIMEOUT)


def _run(receipt_fd: int, argv: list[str]) -> int | None:
    control_fd = sys.stdin.fileno()
    cutoff = time.monotonic() + _MAX_OWNER_SECONDS
    # The controller may have died before the guardian was scheduled.
    if select.select([control_fd], [], [], 0)[0]:
        return None
    try:
        worker = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            pass_fds=(receipt_fd,), start_new_session=True,
        )
    except OSError:
        return None
    finally:
        os.close(receipt_fd)

    while (status := worker.poll()) is None:
        try:
            readable = select.select([control_fd], [], [], 0.025)[0]
            if not readable:
                if time.monotonic() >= cutoff:
                    return _stop(worker, force=False)
                continue
            command = os.read(control_fd, 1)
        except OSError:
            command = b""
        # EOF, including before the controller observes readiness, asks the
        # actual worker parent to terminate the child and collect its status.
        return _stop(worker, force=command == b"K")
    return status


def main() -> int:
    try:
        status = _run(int(sys.argv[1]), sys.argv[2:])
    except subprocess.TimeoutExpired:
        return 1
    if status is not None:
        try:
            print(status, flush=True)
        except BrokenPipeError:
            # The worker was already reaped even if its controller died.
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
