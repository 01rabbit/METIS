"""Verify fixture ownership with real harmless processes."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from metis.evaluation import _fixture_guardian

_GUARDIAN = [sys.executable, "-I", _fixture_guardian.__file__]
_CONTROLLER = """
import os
import subprocess
import sys

result, receipt_fd, *guardian = sys.argv[1:]
with open(result, 'wb') as status:
    process = subprocess.Popen(guardian, stdin=subprocess.PIPE, stdout=status,
                               pass_fds=(int(receipt_fd),))
    # The controller deliberately performs no worker readiness check.
    os.read(0, 1)
os._exit(91)
"""
_WORKER = """
import os
import signal
import sys
import time
from pathlib import Path

ready, ignores_term = sys.argv[1:]
if ignores_term == 'True':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(ready).write_text(str(os.getpid()))
time.sleep(30)
"""


def _await_text(path: Path) -> str:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if path.is_file() and (value := path.read_text().strip()):
            return value
        time.sleep(0.01)
    pytest.fail(f"missing process observation {path.name}")


def test_owner_eof_before_launch_suppresses_worker(tmp_path):
    marker = tmp_path / "started"
    read_fd, write_fd = os.pipe()
    owner_read_fd, owner_write_fd = os.pipe()
    os.close(owner_write_fd)
    try:
        result = subprocess.run(
            [*_GUARDIAN, str(write_fd), sys.executable, "-c",
             f"open({str(marker)!r}, 'w').close()"],
            stdin=owner_read_fd, capture_output=True, pass_fds=(write_fd,), timeout=6, check=True,
        )
    finally:
        os.close(owner_read_fd)
        os.close(read_fd)
        os.close(write_fd)
    assert result.stdout == b""
    assert not marker.exists()


@pytest.mark.parametrize(("ignore_term", "expected"), [
    (False, -signal.SIGTERM), (True, -signal.SIGKILL),
])
def test_controller_exit_between_spawn_and_readiness_reaps_worker(tmp_path, ignore_term, expected):
    ready, status = tmp_path / "worker", tmp_path / "status"
    read_fd, write_fd = os.pipe()
    try:
        with subprocess.Popen(
            [sys.executable, "-I", "-c", _CONTROLLER, str(status), str(write_fd),
             *_GUARDIAN, str(write_fd), sys.executable, "-c", _WORKER, str(ready), str(ignore_term)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, pass_fds=(write_fd,),
        ) as controller:
            try:
                pid = int(_await_text(ready))
            finally:
                controller.kill()
            assert controller.wait(timeout=5) == -signal.SIGKILL
        assert int(_await_text(status)) == expected
        # The guardian prints only after wait() returns, so the worker PID
        # is gone, including any zombie entry.
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_guardian_reports_normal_worker_completion(tmp_path):
    read_fd, write_fd = os.pipe()
    try:
        with subprocess.Popen(
            [*_GUARDIAN, str(write_fd), sys.executable, "-c", "raise SystemExit(75)"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, pass_fds=(write_fd,),
        ) as guardian:
            assert guardian.wait(timeout=6) == 0
            assert guardian.stdout.read() == b"75\n"
    finally:
        os.close(read_fd)
        os.close(write_fd)
