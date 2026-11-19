"""Record and verify a native build identity without executing its artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import shutil
import stat
import subprocess
import time
from dataclasses import asdict, dataclass
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
_DEPENDENCY_LIMIT = 128
_DEPENDENCY_BYTES_LIMIT = 512 * 1024**2
_TOOL_OUTPUT_LIMIT = 1024 * 1024
_PRELOAD_PATH = Path("/etc/ld.so.preload")
_HEX256 = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}")
_SONAME = re.compile(r"[A-Za-z0-9_.+-]{1,255}")
_TARGETS = {("Linux", "aarch64"), ("Linux", "x86_64")}


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
    dependencies: tuple[NativeDependency, ...]


@dataclass(frozen=True, order=True)
class NativeDependency:
    soname: str
    path: str
    size: int
    sha256: str


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
    return _snapshot_hash(path, limit)[1]


def _snapshot_hash(path: Path, limit: int, *, deadline: float | None = None) -> tuple[int, str]:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ValueError("artifact is outside its regular-file or size boundary")
        read = 0
        while chunk := source.read(min(limit - read + 1, 1024**2)):
            if deadline is not None and time.monotonic() >= deadline:
                raise ValueError("native dependency closure deadline exceeded")
            read += len(chunk)
            if read > limit:
                raise ValueError("artifact changed size during verification")
            digest.update(chunk)
        after = os.fstat(source.fileno())
        if (read != before.st_size or (before.st_dev, before.st_ino, before.st_size,
                before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino,
                after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("artifact changed during verification")
        return read, digest.hexdigest()


def _inspect_output(argv: list[str], *, deadline: float) -> str:
    """Run a system metadata reader, never the native server, with bounded output."""
    if deadline <= time.monotonic():
        raise ValueError("native dependency closure deadline exceeded")
    output = bytearray()
    try:
        process = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={"PATH": os.defpath, "LC_ALL": "C", "LANG": "C"}, close_fds=True,
        )
    except OSError:
        raise ValueError("native dependency metadata could not be inspected") from None
    assert process.stdout is not None
    try:
        os.set_blocking(process.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError
                chunk = os.read(process.stdout.fileno(), 65_536)
                if not chunk:
                    selector.unregister(process.stdout)
                    continue
                output.extend(chunk)
                if len(output) > _TOOL_OUTPUT_LIMIT:
                    raise ValueError("native dependency metadata is oversized")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        status = process.wait(timeout=remaining)
    except (OSError, TimeoutError, ValueError):
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            raise ValueError("native dependency metadata reader could not be reaped") from None
        raise ValueError("native dependency metadata is invalid, oversized, or timed out") from None
    finally:
        process.stdout.close()
    if status != 0:
        raise ValueError("native dependency metadata reader failed")
    try:
        return output.decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("native dependency metadata is not ASCII") from None


def _is_ldconfig_header(line: str) -> bool:
    return re.fullmatch(r"\d+ libs? found in cache (?:'/(?:[^'\n]+)'|`/(?:[^'\n]+)')", line) is not None


def _is_ldconfig_footer(line: str) -> bool:
    return re.fullmatch(r"Cache generated by: ldconfig \(GNU libc\) stable release version \d+\.\d+(?:\.\d+)?",
                        line) is not None


def _trusted_system_tool(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
        info = resolved.stat()
    except OSError:
        raise ValueError("native dependency metadata tool is unavailable") from None
    roots = (Path("/usr/bin"), Path("/bin"), Path("/usr/sbin"), Path("/sbin"))
    allowed = False
    for root in roots:
        try:
            allowed = allowed or resolved.is_relative_to(root.resolve(strict=True))
        except OSError:
            continue
    if (not allowed or not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_mode & 0o022 or not os.access(resolved, os.X_OK)):
        raise ValueError("native dependency metadata tool is outside trusted system paths")
    return resolved


def _readelf_tool() -> Path:
    found = shutil.which("readelf", path=os.defpath)
    if found is None:
        raise ValueError("native ELF metadata reader is unavailable")
    return _trusted_system_tool(Path(found))


def _ldconfig_tool() -> Path:
    found = next((path for path in (Path("/usr/sbin/ldconfig"), Path("/sbin/ldconfig"))
                  if path.exists()), None)
    if found is None:
        raise ValueError("native dependency loader cache is unavailable")
    return _trusted_system_tool(found)


def _require_no_ld_preload() -> None:
    try:
        descriptor = os.open(_PRELOAD_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return
    except OSError:
        raise ValueError("native loader preload configuration is unavailable") from None
    with os.fdopen(descriptor, "rb") as source:
        before = _preload_fstat(source.fileno())
        _validate_ld_preload_stat(before)
        if before.st_size > _METADATA_LIMIT:
            raise ValueError("native loader preload configuration is outside its bounds")
        raw = source.read(_METADATA_LIMIT + 1)
        after = _preload_fstat(source.fileno())
        if (len(raw) != before.st_size or len(raw) > _METADATA_LIMIT
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("native loader preload configuration changed during verification")
        if raw.strip():
            raise ValueError("native loader preload configuration must be empty")


def _preload_fstat(descriptor: int) -> os.stat_result:
    return os.fstat(descriptor)


def _validate_ld_preload_stat(info: os.stat_result) -> None:
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022):
        raise ValueError("native loader preload configuration must be root-owned and not group/world writable")
    if info.st_size > _METADATA_LIMIT:
        raise ValueError("native loader preload configuration is outside its bounds")


def _ldconfig_entries(*, deadline: float) -> dict[tuple[str, str], set[Path]]:
    ldconfig = _ldconfig_tool()
    output = _inspect_output([str(ldconfig), "-p"], deadline=deadline)
    entries: dict[tuple[str, str], set[Path]] = {}
    pattern = re.compile(r"^\s*(\S+)\s+\(([^)]*)\)\s+=>\s+(\S+)\s*$")
    for line in output.splitlines():
        match = pattern.fullmatch(line)
        if match is None:
            if (line.strip() and not _is_ldconfig_header(line.strip())
                    and not _is_ldconfig_footer(line.strip())):
                raise ValueError("native dependency loader cache line is ambiguous")
            continue
        name, tags, path = match.groups()
        candidate = Path(path)
        if not candidate.is_absolute():
            raise ValueError("native dependency loader path is not absolute")
        for arch in ("AArch64", "x86-64"):
            if arch in tags:
                try:
                    resolved = candidate.resolve(strict=True)
                except OSError:
                    raise ValueError("native dependency loader path is unavailable") from None
                entries.setdefault((name, arch), set()).add(resolved)
    return entries


def _dependency_closure(binary: Path, *, target_os: str, target_arch: str) -> tuple[NativeDependency, ...]:
    """Hash the bounded recursive ELF DT_NEEDED closure without executing it."""
    if (target_os, target_arch) not in _TARGETS:
        raise ValueError("native dependency closure is unsupported on this target")
    deadline = time.monotonic() + 90
    _require_no_ld_preload()
    readelf = _readelf_tool()
    arch_tag = "AArch64" if target_arch == "aarch64" else "x86-64"
    cache = _ldconfig_entries(deadline=deadline)
    expected_machine = "AArch64" if target_arch == "aarch64" else "Advanced Micro Devices X86-64"

    def check_elf_target(path: Path) -> None:
        header = _inspect_output([str(readelf), "-W", "-h", str(path)], deadline=deadline)
        if (re.search(r"^\s*Class:\s+ELF64\s*$", header, re.MULTILINE) is None
                or re.search(r"^\s*Data:\s+2's complement, little endian\s*$", header, re.MULTILINE) is None
                or re.search(rf"^\s*Machine:\s+{re.escape(expected_machine)}\s*$", header,
                             re.MULTILINE) is None):
            raise ValueError("native ELF dependency target does not match the approved architecture")

    check_elf_target(binary)
    interpreter_output = _inspect_output([str(readelf), "-W", "-l", str(binary)], deadline=deadline)
    dynamic_output = _inspect_output([str(readelf), "-W", "-d", str(binary)], deadline=deadline)
    interpreters = re.findall(r"Requesting program interpreter:\s*([^]\s]+)", interpreter_output)
    if len(interpreters) != 1 or not Path(interpreters[0]).is_absolute():
        raise ValueError("native ELF interpreter is missing or ambiguous")

    def needed_names(output: str) -> tuple[str, ...]:
        unsupported = ("(RPATH)", "(RUNPATH)", "(FILTER)", "(AUXILIARY)", "(AUDIT)", "(DEPAUDIT)")
        if any(tag in output for tag in unsupported):
            raise ValueError("native ELF uses an unsupported dynamic-loader feature")
        names = re.findall(r"\(NEEDED\).*?\[([^]\x00]+)\]", output)
        if (len(names) > _DEPENDENCY_LIMIT or len(set(names)) != len(names)
                or any(not _SONAME.fullmatch(name) for name in names)):
            raise ValueError("native ELF load names are invalid or ambiguous")
        return tuple(names)

    pending: list[tuple[str, Path]] = [("@interpreter", Path(interpreters[0]))]
    pending.extend((name, Path()) for name in needed_names(dynamic_output))
    records: dict[str, NativeDependency] = {}
    resolved_names: dict[str, str] = {}
    total = 0
    while pending:
        if time.monotonic() >= deadline:
            raise ValueError("native dependency closure deadline exceeded")
        name, path = pending.pop(0)
        if name == "@interpreter":
            try:
                path = path.resolve(strict=True)
            except OSError:
                raise ValueError("native ELF interpreter is unavailable") from None
        else:
            matches = cache.get((name, arch_tag), set())
            if len(matches) != 1:
                raise ValueError("native dependency resolution is missing or ambiguous")
            path = next(iter(matches))
        if name in resolved_names:
            if resolved_names[name] != str(path):
                raise ValueError("native dependency name resolves to multiple files")
            continue
        resolved_names[name] = str(path)
        if len(resolved_names) > _DEPENDENCY_LIMIT:
            raise ValueError("native dependency closure exceeds its entry bound")
        prior = next((record for record in records.values() if record.path == str(path)), None)
        if prior is not None:
            continue
        if len(records) >= _DEPENDENCY_LIMIT:
            raise ValueError("native dependency closure exceeds its entry bound")
        try:
            info = path.stat()
        except OSError:
            raise ValueError("native dependency is unavailable") from None
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= _BINARY_LIMIT:
            raise ValueError("native dependency is outside its regular-file or size boundary")
        if total + info.st_size > _DEPENDENCY_BYTES_LIMIT:
            raise ValueError("native dependency closure exceeds its aggregate size bound")
        check_elf_target(path)
        size, digest = _snapshot_hash(path, _BINARY_LIMIT, deadline=deadline)
        if size != info.st_size:
            raise ValueError("native dependency changed during verification")
        total += size
        records[name] = NativeDependency(name, str(path), size, digest)
        child_dynamic = _inspect_output([str(readelf), "-W", "-d", str(path)], deadline=deadline)
        pending.extend((child, Path()) for child in needed_names(child_dynamic))
    return tuple(sorted(records.values()))


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("duplicate manifest field")
    return fields


def _record(raw: bytes) -> NativeBuildIdentity:
    value = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_fields)
    fields = ("source_commit", "patch_sha256", "binary_sha256", "target_os", "target_arch",
              "compiler_id", "compiler_version", "cmake_version")
    if (not isinstance(value, dict) or set(value) != {*fields, "version", "profile", "dependencies"}
            or type(value["version"]) is not int or value["version"] != 2
            or value["profile"] != _PROFILE
            or any(not isinstance(value[field], str) for field in fields)):
        raise ValueError("unrecognized native build manifest")
    dependencies_raw = value["dependencies"]
    if not isinstance(dependencies_raw, list) or len(dependencies_raw) > _DEPENDENCY_LIMIT:
        raise ValueError("native dependency manifest is outside its bounds")
    dependencies = []
    for entry in dependencies_raw:
        if (not isinstance(entry, dict) or set(entry) != {"soname", "path", "size", "sha256"}
                or not isinstance(entry["soname"], str)
                or (entry["soname"] != "@interpreter" and not _SONAME.fullmatch(entry["soname"]))
                or not isinstance(entry["path"], str) or not Path(entry["path"]).is_absolute()
                or type(entry["size"]) is not int or not 0 < entry["size"] <= _BINARY_LIMIT
                or not isinstance(entry["sha256"], str) or not _HEX256.fullmatch(entry["sha256"])):
            raise ValueError("invalid native dependency manifest entry")
        dependencies.append(NativeDependency(entry["soname"], entry["path"], entry["size"], entry["sha256"]))
    if (dependencies != sorted(dependencies)
            or len({item.soname for item in dependencies}) != len(dependencies)
            or len({item.path for item in dependencies}) != len(dependencies)
            or sum(item.size for item in dependencies) > _DEPENDENCY_BYTES_LIMIT):
        raise ValueError("native dependency manifest is ambiguous or non-canonical")
    record = NativeBuildIdentity(
        source_commit=value["source_commit"], patch_sha256=value["patch_sha256"],
        binary_sha256=value["binary_sha256"], target_os=value["target_os"],
        target_arch=value["target_arch"], compiler_id=value["compiler_id"],
        compiler_version=value["compiler_version"], cmake_version=value["cmake_version"],
        dependencies=tuple(dependencies),
    )
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
    """Check executable, declared ELF dependency closure, and model against an approved record."""
    if _hash(binary, _BINARY_LIMIT) != record.binary_sha256:
        raise ValueError("native binary digest mismatch")
    if _dependency_closure(binary, target_os=record.target_os,
                           target_arch=record.target_arch) != record.dependencies:
        raise ValueError("native dependency closure changed after approval")
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
    target_os = _cmake_value(system, "CMAKE_SYSTEM_NAME")
    binary = build / "bin" / "llama-server"
    dependencies = _dependency_closure(binary, target_os=target_os, target_arch=target_arch)
    payload = {
        "version": 2, "source_commit": source_commit, "profile": _PROFILE,
        "patch_sha256": _hash(patch, _METADATA_LIMIT),
        "binary_sha256": _hash(binary, _BINARY_LIMIT),
        "target_os": target_os, "target_arch": target_arch,
        "compiler_id": _cmake_value(compiler, "CMAKE_CXX_COMPILER_ID"),
        "compiler_version": _cmake_value(compiler, "CMAKE_CXX_COMPILER_VERSION"),
        "cmake_version": systems[0].parent.name,
        "dependencies": [asdict(item) for item in dependencies],
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
