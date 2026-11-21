#!/usr/bin/env python3
"""Write a content-addressed manifest for a trace-only llama-server build."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import sys
from pathlib import Path

SOURCE_COMMIT = "b1b770d90d94cad9e9ea5b993bdbc383a522fb28"
TRACE_PATCH_SHA256 = "c97500f6a98a2c34554953f82eb46ce6b39d1b82581fa1aef65b197090dd1c4c"


def digest(path: Path, limit: int) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError("trace build artifact is outside size/type boundary")
        hasher = hashlib.sha256()
        total = 0
        with os.fdopen(fd, "rb") as source:
            fd = -1
            while chunk := source.read(min(1024 * 1024, limit - total + 1)):
                total += len(chunk)
                if total > limit:
                    raise ValueError("trace build artifact exceeded size boundary")
                hasher.update(chunk)
        if total != info.st_size:
            raise ValueError("trace build artifact changed while hashing")
        return hasher.hexdigest()
    finally:
        if fd >= 0:
            os.close(fd)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: write_llama_work_trace_manifest.py BUILD_DIRECTORY", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve(strict=True)
    binary = root / "build/bin/llama-server"
    patch = root / "llama-work-trace.patch"
    patch_digest = digest(patch, 1024 * 1024)
    if patch_digest != TRACE_PATCH_SHA256:
        raise ValueError("trace patch does not match the repository-pinned patch")
    value = {
        "version": 1,
        "source_commit": SOURCE_COMMIT,
        "trace_patch_sha256": patch_digest,
        "binary_sha256": digest(binary, 128 * 1024 * 1024),
        "target_os": platform.system(),
        "target_arch": platform.machine(),
    }
    if value["target_os"] not in {"Darwin", "Linux"}:
        raise ValueError("unsupported trace build target")
    destination = root / "trace-build.json"
    temp = root / ".trace-build.json.tmp"
    temp.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    temp.replace(destination)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
