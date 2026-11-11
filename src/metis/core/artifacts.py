"""Copy bounded regular artifacts through directory descriptors, never symlinks."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path, PurePosixPath


def read_artifact(root: Path, relative: str, *, max_bytes: int = 1_048_576) -> bytes:
    """Read a bounded snapshot, with no symlink components (Linux/macOS).

    The controller chooses a trusted root. The resulting bytes, not a mutable
    host path, are passed to the runtime. Directory renames cannot redirect the
    descriptors. This is not safe archive extraction or a sandbox by itself.
    """
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
            content = stream.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise ValueError("artifact exceeds byte limit")
            return content
    finally:
        os.close(directory)


def artifact_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
