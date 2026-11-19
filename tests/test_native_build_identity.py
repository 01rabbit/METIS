import errno
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from metis.evaluation import native_build_identity as identity


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def build_inputs(tmp_path, monkeypatch):
    build = tmp_path / "build"
    info = build / "CMakeFiles" / "4.4.2"
    info.mkdir(parents=True)
    (info / "CMakeSystem.cmake").write_text(
        'set(CMAKE_SYSTEM_NAME "Linux")\n'
        'set(CMAKE_SYSTEM_PROCESSOR "aarch64")\n'
        'set(CMAKE_CROSSCOMPILING "FALSE")\n'
    )
    (info / "CMakeCXXCompiler.cmake").write_text(
        'set(CMAKE_CXX_COMPILER_ID "AppleClang")\n'
        'set(CMAKE_CXX_COMPILER_VERSION "21.0.0")\n'
    )
    (build / "CMakeCache.txt").write_text(
        "\n".join(f"{key}:STRING={value}" for key, value in identity._PROFILE.items())
        + "\nCMAKE_OSX_ARCHITECTURES:STRING=\n"
    )
    binary = build / "bin" / "llama-server"
    binary.parent.mkdir()
    binary.write_bytes(b"fixture executable bytes")
    patch = tmp_path / "llama-server.patch"
    patch.write_bytes(b"fixture patch bytes")
    model = tmp_path / "fixture.gguf"
    model.write_bytes(b"fixture model bytes")
    monkeypatch.setattr(identity, "_PUBLIC_MODEL_SHA256", _sha(model))
    dependency = tmp_path / "libfixture.so"
    dependency.write_bytes(b"fixture native dependency")

    def dependency_closure(_binary, *, target_os, target_arch):
        assert (target_os, target_arch) == ("Linux", "aarch64")
        size, digest = identity._snapshot_hash(dependency, identity._BINARY_LIMIT)
        return (identity.NativeDependency("libfixture.so", str(dependency), size, digest),)

    monkeypatch.setattr(identity, "_dependency_closure", dependency_closure)
    return build, binary, patch, model


@pytest.fixture
def approved(tmp_path, build_inputs):
    build, binary, patch, model = build_inputs
    manifest = tmp_path / "native-build.json"
    identity.write_native_build_manifest(build, source_commit=identity._SOURCE_COMMIT, patch=patch, output=manifest)
    return manifest, {
        "expected_manifest_sha256": _sha(manifest), "binary": binary, "patch": patch,
        "model": model, "target_os": "Linux", "target_arch": "aarch64",
    }


def test_verify_trusted_manifest_without_executing_artifacts(approved, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("offline verification attempted to execute an artifact")

    monkeypatch.setattr(subprocess, "Popen", unexpected)
    manifest, settings = approved
    result = identity.verify_native_build(manifest, **settings)
    assert result.binary_sha256 == _sha(settings["binary"])
    assert result.patch_sha256 == _sha(settings["patch"])
    assert (result.target_os, result.target_arch, result.compiler_version) == ("Linux", "aarch64", "21.0.0")


@pytest.mark.parametrize(("field", "message"), [
    ("binary", "binary digest mismatch"),
    ("patch", "patch digest mismatch"),
    ("model", "registered single-file"),
])
def test_verify_rejects_substitution(approved, field, message):
    manifest, settings = approved
    settings[field].write_bytes(b"substituted bytes, possibly a GGUF shard")
    with pytest.raises(ValueError, match=message):
        identity.verify_native_build(manifest, **settings)


def test_self_consistent_foreign_manifest_does_not_replace_trusted_digest(approved):
    manifest, settings = approved
    settings["binary"].write_bytes(b"substituted executable")
    record = json.loads(manifest.read_text())
    record["binary_sha256"] = _sha(settings["binary"])
    manifest.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="trusted digest"):
        identity.verify_native_build(manifest, **settings)


@pytest.mark.parametrize(("field", "value"), [
    ("version", True), ("source_commit", "0" * 40), ("target_arch", "arbitrary"),
    ("profile", {"GGML_BACKEND_DL": "ON"}), ("compiler_id", "/unexpected/path"), ("extra", True),
])
def test_even_a_matching_digest_requires_the_schema_and_build_profile(approved, field, value):
    manifest, settings = approved
    record = json.loads(manifest.read_text())
    record[field] = value
    manifest.write_text(json.dumps(record))
    settings["expected_manifest_sha256"] = _sha(manifest)
    with pytest.raises(ValueError):
        identity.verify_native_build(manifest, **settings)


def test_duplicate_build_fields_are_rejected(approved):
    manifest, settings = approved
    manifest.write_text(manifest.read_text().replace('"version": 2', '"version": 1, "version": 2'))
    settings["expected_manifest_sha256"] = _sha(manifest)
    with pytest.raises(ValueError, match="duplicate"):
        identity.verify_native_build(manifest, **settings)


def test_environment_must_match_approved_target(approved):
    manifest, settings = approved
    settings.update(target_os="Linux", target_arch="x86_64")
    with pytest.raises(ValueError, match="requested environment"):
        identity.verify_native_build(manifest, **settings)


def test_symlink_fifo_and_oversized_artifacts_are_rejected(approved, tmp_path):
    manifest, settings = approved
    alias = tmp_path / "alias"
    alias.symlink_to(settings["binary"])
    with pytest.raises(OSError) as error:
        identity.verify_native_build(manifest, **{**settings, "binary": alias})
    assert error.value.errno == errno.ELOOP
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="regular-file"):
        identity.verify_native_build(manifest, **{**settings, "binary": fifo})
    with settings["model"].open("wb") as oversized:
        oversized.truncate(2 * 1024**2 + 1)
    with pytest.raises(ValueError, match="size boundary"):
        identity.verify_native_build(manifest, **settings)


@pytest.mark.parametrize(("file", "old", "new"), [
    ("CMakeCache.txt", "GGML_METAL:STRING=OFF", "GGML_METAL:STRING=ON"),
    ("CMakeCache.txt", "GGML_METAL:STRING=OFF", "GGML_METAL:STRING=OFF\nGGML_METAL:BOOL=ON"),
    ("CMakeCache.txt", "CMAKE_OSX_ARCHITECTURES:STRING=", "CMAKE_OSX_ARCHITECTURES:STRING=arm64;x86_64"),
    ("CMakeFiles/4.4.2/CMakeSystem.cmake", 'CMAKE_CROSSCOMPILING "FALSE"', 'CMAKE_CROSSCOMPILING "TRUE"'),
])
def test_observation_does_not_write_a_manifest_for_an_unexpected_build(
    build_inputs, tmp_path, file, old, new,
):
    build, _, patch, _ = build_inputs
    affected = build / file
    affected.write_text(affected.read_text().replace(old, new))
    output = tmp_path / "native-build.json"
    with pytest.raises(ValueError):
        identity.write_native_build_manifest(build, source_commit=identity._SOURCE_COMMIT, patch=patch, output=output)
    assert not output.exists()


@pytest.mark.parametrize("python_present", [False, True])
def test_builder_checks_python_before_starting_a_build(tmp_path, python_present):
    if python_present:
        old_python = tmp_path / "python3"
        old_python.write_text("#!/bin/sh\nexit 1\n")
        old_python.chmod(0o700)
    build_script = Path(__file__).resolve().parents[1] / "scripts" / "build_llama_work_budget.sh"
    destination = tmp_path / "new-build"
    result = subprocess.run(
        ["/bin/sh", str(build_script), str(destination)], env={"PATH": str(tmp_path)},
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert result.returncode == 2
    assert "Python 3.12 or newer" in result.stderr
    assert not destination.exists()


def test_builder_refuses_unsupported_platform_before_network_or_build(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "python3").symlink_to(sys.executable)
    dirname = Path(shutil.which("dirname", path=os.defpath) or "/usr/bin/dirname")
    (tools / "dirname").symlink_to(dirname)
    uname = tools / "uname"
    uname.write_text("#!/bin/sh\n[ \"$1\" = -m ] && echo arm64 || echo Darwin\n")
    uname.chmod(0o700)
    build_script = Path(__file__).resolve().parents[1] / "scripts" / "build_llama_work_budget.sh"
    destination = tmp_path / "not-started"
    result = subprocess.run(["/bin/sh", str(build_script), str(destination)],
                            env={"PATH": str(tools)}, capture_output=True, text=True,
                            timeout=5, check=False)
    assert result.returncode == 2
    assert "supports Linux aarch64 and x86_64 only" in result.stderr
    assert not destination.exists()


def test_dependency_closure_rejects_ambiguous_or_unsupported_loader_features(tmp_path, monkeypatch):
    binary = tmp_path / "server"
    binary.write_bytes(b"not executed")
    library_a = tmp_path / "liba.so"
    library_b = tmp_path / "libb.so"
    interpreter = tmp_path / "ld-linux"
    for path in (library_a, library_b, interpreter):
        path.write_bytes(path.name.encode())
    monkeypatch.setattr(identity, "_readelf_tool", lambda: Path("/usr/bin/readelf"))
    monkeypatch.setattr(identity, "_require_no_ld_preload", lambda: None)
    monkeypatch.setattr(identity, "_ldconfig_entries", lambda **_kwargs: {
        ("liba.so", "AArch64"): {library_a},
        ("libb.so", "AArch64"): {library_b},
        ("ld-linux-aarch64.so.1", "AArch64"): {interpreter.resolve()},
    })

    def metadata(argv, *, deadline):
        assert deadline > 0
        if argv[1:3] == ["-W", "-h"]:
            return "Class: ELF64\nData: 2's complement, little endian\nMachine: AArch64\n"
        if argv[1:3] == ["-W", "-l"]:
            return f"Requesting program interpreter: {interpreter}]\n"
        path = Path(argv[-1])
        if path == binary:
            return "(NEEDED) Shared library: [liba.so]\n"
        if path == library_a:
            return "(NEEDED) Shared library: [libb.so]\n"
        if path == interpreter:
            return "(NEEDED) Shared library: [ld-linux-aarch64.so.1]\n"
        return ""

    monkeypatch.setattr(identity, "_inspect_output", metadata)
    closure = identity._dependency_closure(binary, target_os="Linux", target_arch="aarch64")
    assert [item.soname for item in closure] == ["@interpreter", "liba.so", "libb.so"]
    assert all(len(item.sha256) == 64 for item in closure)

    monkeypatch.setattr(identity, "_ldconfig_entries", lambda **_kwargs: {
        ("liba.so", "AArch64"): {library_a, library_b},
        ("libb.so", "AArch64"): {library_b},
    })
    with pytest.raises(ValueError, match="missing or ambiguous"):
        identity._dependency_closure(binary, target_os="Linux", target_arch="aarch64")

    monkeypatch.setattr(identity, "_ldconfig_entries", lambda **_kwargs: {
        ("liba.so", "AArch64"): {library_a},
        ("libb.so", "AArch64"): {library_b},
    })
    monkeypatch.setattr(identity, "_inspect_output", lambda argv, **kwargs: (
        metadata(argv, **kwargs) + "(RUNPATH) Library runpath: [$ORIGIN]\n"
        if argv[1:3] == ["-W", "-d"] and Path(argv[-1]) == binary else metadata(argv, **kwargs)
    ))
    with pytest.raises(ValueError, match="unsupported dynamic-loader"):
        identity._dependency_closure(binary, target_os="Linux", target_arch="aarch64")

    with pytest.raises(ValueError, match="unsupported on this target"):
        identity._dependency_closure(binary, target_os="Darwin", target_arch="arm64")


@pytest.mark.parametrize("header", [
    "432 libs found in cache '/etc/ld.so.cache'",
    "432 libs found in cache `/etc/ld.so.cache'",
    "1 lib found in cache `/etc/ld.so.cache'",
])
def test_ldconfig_cache_header_accepts_only_known_quote_forms(header):
    assert identity._is_ldconfig_header(header)
    assert not identity._is_ldconfig_header(header.replace("/etc/ld.so.cache", "relative/cache"))
    assert not identity._is_ldconfig_header(header + " trailing")


def test_ldconfig_cache_footer_is_exact():
    assert identity._is_ldconfig_footer(
        "Cache generated by: ldconfig (GNU libc) stable release version 2.36"
    )
    assert not identity._is_ldconfig_footer(
        "Cache generated by: ldconfig (GNU libc) stable release version 2.36 injected"
    )


def test_missing_ld_preload_is_accepted(tmp_path, monkeypatch):
    preload = tmp_path / "ld.so.preload"
    monkeypatch.setattr(identity, "_PRELOAD_PATH", preload)
    identity._require_no_ld_preload()


@pytest.mark.parametrize("content", [b"", b"/tmp/unreviewed.so\n"])
def test_root_owned_ld_preload_must_be_empty(tmp_path, monkeypatch, content):
    preload = tmp_path / "ld.so.preload"
    monkeypatch.setattr(identity, "_PRELOAD_PATH", preload)
    preload.write_bytes(content)
    real_fstat = os.fstat

    def root_owned_fstat(descriptor):
        info = real_fstat(descriptor)
        return SimpleNamespace(
            st_dev=info.st_dev, st_ino=info.st_ino, st_size=info.st_size,
            st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns,
            st_mode=info.st_mode, st_uid=0,
        )

    monkeypatch.setattr(identity, "_preload_fstat", root_owned_fstat)
    if content:
        with pytest.raises(ValueError, match="must be empty"):
            identity._require_no_ld_preload()
    else:
        identity._require_no_ld_preload()


@pytest.mark.parametrize(("uid", "mode"), [(501, 0o600), (0, 0o622)])
def test_ld_preload_rejects_untrusted_owner_or_permissions(uid, mode):
    metadata = SimpleNamespace(st_mode=stat.S_IFREG | mode, st_uid=uid, st_size=0)
    with pytest.raises(ValueError, match="root-owned"):
        identity._validate_ld_preload_stat(metadata)


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_ld_preload_rejects_nonregular_paths(tmp_path, monkeypatch, kind):
    preload = tmp_path / "ld.so.preload"
    monkeypatch.setattr(identity, "_PRELOAD_PATH", preload)
    if kind == "symlink":
        target = tmp_path / "target"
        target.write_bytes(b"")
        preload.symlink_to(target)
    else:
        os.mkfifo(preload)
    with pytest.raises(ValueError):
        identity._require_no_ld_preload()


@pytest.mark.skipif(
    not sys.platform.startswith("linux") or platform.machine() not in {"aarch64", "x86_64"}
    or platform.libc_ver()[0] != "glibc"
    or shutil.which("readelf", path=os.defpath) is None
    or not any(Path(path).exists() for path in ("/usr/sbin/ldconfig", "/sbin/ldconfig")),
    reason="requires glibc Linux with supported readelf and ldconfig tools",
)
def test_linux_system_elf_dependency_closure_uses_real_metadata_tools():
    binary = Path("/bin/true")
    if not binary.exists():
        pytest.skip("system test binary unavailable")
    closure = identity._dependency_closure(
        binary, target_os="Linux", target_arch=platform.machine(),
    )
    assert closure
    assert closure[0].soname == "@interpreter"
    assert len({item.path for item in closure}) == len(closure)


def test_expired_closure_deadline_refuses_before_metadata_tool(tmp_path, monkeypatch):
    called = False

    def unexpected(*_args, **_kwargs):
        nonlocal called
        called = True
        pytest.fail("expired deadline started a metadata tool")

    monkeypatch.setattr(identity.subprocess, "Popen", unexpected)
    monkeypatch.setattr(identity.time, "monotonic", lambda: 10.0)
    with pytest.raises(ValueError, match="deadline exceeded"):
        identity._inspect_output(["readelf", "-W", "-d", str(tmp_path / "server")], deadline=9.0)
    assert not called


@pytest.mark.parametrize("mode", ["oversized", "timeout"])
def test_metadata_tool_output_and_runtime_are_bounded(monkeypatch, mode):
    processes = []
    original_popen = identity.subprocess.Popen

    def tracked_popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(identity.subprocess, "Popen", tracked_popen)
    if mode == "oversized":
        code = "import sys; sys.stdout.write('x' * 1100000)"
        deadline = identity.time.monotonic() + 5
        message = "oversized"
    else:
        code = "import time; time.sleep(10)"
        deadline = identity.time.monotonic() + 0.1
        message = "timed out"
    with pytest.raises(ValueError, match=message):
        identity._inspect_output([sys.executable, "-c", code], deadline=deadline)
    assert len(processes) == 1 and processes[0].poll() is not None


@pytest.mark.parametrize("mutation", [
    lambda item: {**item, "path": "relative/library.so"},
    lambda item: {**item, "size": True},
    lambda item: {**item, "sha256": "not-a-digest"},
    lambda item: {**item, "extra": "ignored fields are forbidden"},
])
def test_dependency_manifest_entry_is_strict(approved, mutation):
    manifest, settings = approved
    value = json.loads(manifest.read_text())
    value["dependencies"][0] = mutation(value["dependencies"][0])
    manifest.write_text(json.dumps(value))
    settings["expected_manifest_sha256"] = _sha(manifest)
    with pytest.raises(ValueError, match="dependency manifest|unrecognized"):
        identity.verify_native_build(manifest, **settings)


def test_dependency_manifest_rejects_noncanonical_order_and_duplicate_paths(approved):
    manifest, settings = approved
    value = json.loads(manifest.read_text())
    original = value["dependencies"][0]
    second = {**original, "soname": "libother.so"}
    value["dependencies"] = [second, original]
    manifest.write_text(json.dumps(value))
    settings["expected_manifest_sha256"] = _sha(manifest)
    with pytest.raises(ValueError, match="ambiguous or non-canonical"):
        identity.verify_native_build(manifest, **settings)


def test_reserved_interpreter_dependency_name_is_valid_in_manifest(approved):
    manifest, _settings = approved
    value = json.loads(manifest.read_text())
    value["dependencies"][0]["soname"] = "@interpreter"
    record = identity._record(json.dumps(value).encode("ascii"))
    assert record.dependencies[0].soname == "@interpreter"
