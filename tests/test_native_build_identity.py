import errno
import hashlib
import json
import os
import subprocess
from pathlib import Path

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
        'set(CMAKE_SYSTEM_NAME "Darwin")\n'
        'set(CMAKE_SYSTEM_PROCESSOR "arm64")\n'
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
    return build, binary, patch, model


@pytest.fixture
def approved(tmp_path, build_inputs):
    build, binary, patch, model = build_inputs
    manifest = tmp_path / "native-build.json"
    identity.write_native_build_manifest(build, source_commit=identity._SOURCE_COMMIT, patch=patch, output=manifest)
    return manifest, {
        "expected_manifest_sha256": _sha(manifest), "binary": binary, "patch": patch,
        "model": model, "target_os": "Darwin", "target_arch": "arm64",
    }


def test_verify_trusted_manifest_without_executing_artifacts(approved, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("offline verification attempted to execute an artifact")

    monkeypatch.setattr(subprocess, "Popen", unexpected)
    manifest, settings = approved
    result = identity.verify_native_build(manifest, **settings)
    assert result.binary_sha256 == _sha(settings["binary"])
    assert result.patch_sha256 == _sha(settings["patch"])
    assert (result.target_os, result.target_arch, result.compiler_version) == ("Darwin", "arm64", "21.0.0")


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
    manifest.write_text(manifest.read_text().replace('"version": 1', '"version": 2, "version": 1'))
    settings["expected_manifest_sha256"] = _sha(manifest)
    with pytest.raises(ValueError, match="duplicate"):
        identity.verify_native_build(manifest, **settings)


def test_environment_must_match_approved_target(approved):
    manifest, settings = approved
    settings.update(target_os="Linux", target_arch="aarch64")
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
