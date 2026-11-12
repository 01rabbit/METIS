"""Copy bounded regular artifacts through directory descriptors, never symlinks."""
from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO


@contextmanager
def artifact_stream(root: Path, relative: str, *, max_bytes: int) -> Iterator[BinaryIO]:
    """Open a scoped regular file through non-symlink directory descriptors."""
    path = PurePosixPath(relative)
    if (not relative or relative == "." or path.is_absolute()
            or ".." in path.parts or "\\" in relative or ":" in relative
            or "\x00" in relative or max_bytes < 1):
        raise ValueError("invalid relative artifact path or limit")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > max_bytes:
                raise ValueError("artifact must be a bounded regular file")
            yield stream
    finally:
        os.close(directory)


def read_artifact(root: Path, relative: str, *, max_bytes: int = 1_048_576) -> bytes:
    """Read bounded bytes without following symlink components or special files."""
    with artifact_stream(root, relative, max_bytes=max_bytes) as stream:
        content = stream.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise ValueError("artifact exceeds byte limit")
        return content


def artifact_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
