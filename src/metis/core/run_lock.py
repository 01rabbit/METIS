"""Per-run exclusive lock: the controller is the single writer of a run.

Budget reservation, event sequences and official submissions of one run are taken
under this lock, so concurrent workers or a restarted job cannot overspend the
budget, collide on sequence numbers or submit twice in parallel. The lock is an
advisory ``flock`` on ``<state>/locks/<run_id>.lock`` (released by the OS when a
process dies) and re-entrant within one thread.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path

_local = threading.local()


@contextlib.contextmanager
def run_lock(database: Path, run_id: str, *, timeout: float = 60.0) -> Iterator[None]:
    if not re.fullmatch(r"[0-9A-Za-z_-]{1,80}", run_id):
        raise ValueError("invalid run id")
    held: dict[str, int] = getattr(_local, "held", None) or {}
    _local.held = held
    key = f"{database.resolve()}:{run_id}"
    if held.get(key):
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    directory = database.parent / "locks"
    directory.mkdir(mode=0o700, exist_ok=True)
    descriptor = os.open(directory / f"{run_id}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("run is busy (another controller operation holds its lock)") from None
                time.sleep(0.05)
        held[key] = 1
        try:
            yield
        finally:
            held.pop(key, None)
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def operation_lock(database: Path, run_id: str, *, timeout: float = 480.0) -> Iterator[None]:
    """Serialize one run's bounded tool operations without blocking cancellation.

    Unlike ``run_lock``, this lock is not taken by cancellation or recovery. Those
    paths can therefore stop a registered sandbox worker while an operation is
    running. Its longer timeout covers the maximum sandbox workload plus teardown.
    """
    if not re.fullmatch(r"[0-9A-Za-z_-]{1,80}", run_id):
        raise ValueError("invalid run id")
    held: dict[str, int] = getattr(_local, "operations_held", None) or {}
    _local.operations_held = held
    key = f"{database.resolve()}:{run_id}"
    if held.get(key):
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    directory = database.parent / "operations"
    directory.mkdir(mode=0o700, exist_ok=True)
    descriptor = os.open(directory / f"{run_id}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("run tool operation exceeded its bounded wait") from None
                time.sleep(0.05)
        held[key] = 1
        try:
            yield
        finally:
            held.pop(key, None)
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def locked(method):  # type: ignore[no-untyped-def]
    """Decorator for CodexSession/WebWorkflow methods whose first argument is run_id."""
    def wrapper(self, run_id, *args, **kwargs):  # type: ignore[no-untyped-def]
        with run_lock(self.database, run_id):
            return method(self, run_id, *args, **kwargs)
    wrapper.__name__ = method.__name__
    wrapper.__doc__ = method.__doc__
    wrapper.__wrapped__ = method  # type: ignore[attr-defined]
    return wrapper
