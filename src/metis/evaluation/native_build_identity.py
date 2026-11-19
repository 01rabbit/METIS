"""Record and verify a native build identity without executing its artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

_SOURCE_COMMIT = "b1b770d90d94cad9e9ea5b993bdbc383a522fb28"
_PUBLIC_MODEL_SHA256 = "270cba1bd5109f42d03350f60406024560464db173c0e387d91f0426d3bd256d"
_PROFILE = {
    "CMAKE_BUILD_TYPE": "Release",
    **dict.fromkeys((
        "BUILD_SHARED_LIBS", "GGML_BACKEND_DL", "GGML_METAL", "GGML_BLAS",
        "GGML_OPENMP", "GGML_NATIVE", "LLAMA_BUILD_APP", "LLAMA_BUILD_EXAMPLES",
        "LLAMA_BUILD_TESTS", "LLAMA_BUILD_UI", "LLAMA_USE_PREBUILT_UI",
        "LLAMA_SUBPROCESS", "LLAMA_OPENSSL",
    ), "OFF"),
}
_METADATA_LIMIT = 256 * 1024
_BINARY_LIMIT = 128 * 1024**2
_HEX256 = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}")
_TARGETS = {("Darwin", "arm64"), ("Linux", "aarch64"), ("Linux", "x86_64")}


@dataclass(frozen=True)
class NativeBuildIdentity:
    source_commit: str
    patch_sha256: str
    binary_sha256: str
    target_os: str
    target_arch: str
    compiler_id: str
    compiler_version: str
    cmake_version: str


def _open_regular(path: Path, limit: int) -> BinaryIO:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError("artifact is outside its regular-file or size boundary")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def _read(path: Path, limit: int) -> bytes:
    with _open_regular(path, limit) as source:
        contents = source.read(limit + 1)
    if not 0 < len(contents) <= limit:
        raise ValueError("artifact changed size during verification")
    return contents


def _hash(path: Path, limit: int) -> str:
    digest = hashlib.sha256()
    remaining = limit
    with _open_regular(path, limit) as source:
        while chunk := source.read(min(remaining + 1, 1024**2)):
            remaining -= len(chunk)
            if remaining < 0:
                raise ValueError("artifact changed size during verification")
            digest.update(chunk)
    if remaining == limit:
        raise ValueError("artifact changed size during verification")
    return digest.hexdigest()


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("duplicate manifest field")
    return fields


def _record(raw: bytes) -> NativeBuildIdentity:
    value = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_fields)
    fields = ("source_commit", "patch_sha256", "binary_sha256", "target_os", "target_arch",
              "compiler_id", "compiler_version", "cmake_version")
    if (not isinstance(value, dict) or set(value) != {*fields, "version", "profile"}
            or type(value["version"]) is not int or value["version"] != 1
            or value["profile"] != _PROFILE
            or any(not isinstance(value[field], str) for field in fields)):
        raise ValueError("unrecognized native build manifest")
    record = NativeBuildIdentity(*(value[field] for field in fields))
    if (record.source_commit != _SOURCE_COMMIT
            or not _HEX256.fullmatch(record.patch_sha256) or not _HEX256.fullmatch(record.binary_sha256)
            or (record.target_os, record.target_arch) not in _TARGETS
            or any(not _ID.fullmatch(item)
                   for item in (record.compiler_id, record.compiler_version, record.cmake_version))):
        raise ValueError("native build identity is outside the approved profile")
    return record


def read_approved_native_build(
    manifest: Path, *, expected_manifest_sha256: str, patch: Path,
    target_os: str, target_arch: str,
) -> NativeBuildIdentity:
    """Check a build record and patch against independently supplied approval."""
    if not _HEX256.fullmatch(expected_manifest_sha256):
        raise ValueError("invalid expected manifest digest")
    raw = _read(manifest, _METADATA_LIMIT)
    if hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
        raise ValueError("manifest does not match trusted digest")
    record = _record(raw)
    if (record.target_os, record.target_arch) != (target_os, target_arch):
        raise ValueError("native build target does not match requested environment")
    if _hash(patch, _METADATA_LIMIT) != record.patch_sha256:
        raise ValueError("native patch digest mismatch")
    return record


def verify_native_runtime(record: NativeBuildIdentity, *, binary: Path, model: Path) -> None:
    """Check executable and model bytes against an already verified record."""
    if _hash(binary, _BINARY_LIMIT) != record.binary_sha256:
        raise ValueError("native binary digest mismatch")
    if _hash(model, 2 * 1024**2) != _PUBLIC_MODEL_SHA256:
        raise ValueError("model is outside the registered single-file public fixture")


def verify_native_build(
    manifest: Path, *, expected_manifest_sha256: str, binary: Path, patch: Path, model: Path,
    target_os: str, target_arch: str,
) -> NativeBuildIdentity:
    """Verify artifacts against a manifest digest supplied from trusted evidence."""
    record = read_approved_native_build(
        manifest, expected_manifest_sha256=expected_manifest_sha256, patch=patch,
        target_os=target_os, target_arch=target_arch,
    )
    verify_native_runtime(record, binary=binary, model=model)
    return record


def _cmake_value(text: str, name: str) -> str:
    matches = re.findall(rf'^set\({name} "([^"\n]*)"\)$', text, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError("missing or ambiguous CMake build metadata")
    return matches[0]


def write_native_build_manifest(build: Path, *, source_commit: str, patch: Path, output: Path) -> None:
    """Write observations from a fresh native build, without executing the binary."""
    cache = _read(build / "CMakeCache.txt", _METADATA_LIMIT).decode("utf-8")
    options = {
        key: re.findall(rf'^{key}:[^=\n]+=(.*)$', cache, re.MULTILINE)
        for key in (*_PROFILE, "CMAKE_OSX_ARCHITECTURES")
    }
    if any(options[key] != [required] for key, required in _PROFILE.items()):
        raise ValueError("CMake build options do not match the recorded profile")
    systems = sorted((build / "CMakeFiles").glob("*/CMakeSystem.cmake"))
    if len(systems) != 1:
        raise ValueError("missing or ambiguous CMake target metadata")
    system = _read(systems[0], _METADATA_LIMIT).decode("utf-8")
    compiler = _read(systems[0].with_name("CMakeCXXCompiler.cmake"), _METADATA_LIMIT).decode("utf-8")
    target_arch = _cmake_value(system, "CMAKE_SYSTEM_PROCESSOR")
    if _cmake_value(system, "CMAKE_CROSSCOMPILING") != "FALSE" or options["CMAKE_OSX_ARCHITECTURES"] not in (
        [], [""], [target_arch],
    ):
        raise ValueError("cross-compiled or multi-architecture build is outside the fixture profile")
    payload = {
        "version": 1, "source_commit": source_commit, "profile": _PROFILE,
        "patch_sha256": _hash(patch, _METADATA_LIMIT),
        "binary_sha256": _hash(build / "bin" / "llama-server", _BINARY_LIMIT),
        "target_os": _cmake_value(system, "CMAKE_SYSTEM_NAME"), "target_arch": target_arch,
        "compiler_id": _cmake_value(compiler, "CMAKE_CXX_COMPILER_ID"),
        "compiler_version": _cmake_value(compiler, "CMAKE_CXX_COMPILER_VERSION"),
        "cmake_version": systems[0].parent.name,
    }
    raw = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("ascii")
    _record(raw)
    with output.open("xb") as destination:
        destination.write(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("source_commit")
    parser.add_argument("patch", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    write_native_build_manifest(args.build, source_commit=args.source_commit, patch=args.patch, output=args.output)


if __name__ == "__main__":
    main()
