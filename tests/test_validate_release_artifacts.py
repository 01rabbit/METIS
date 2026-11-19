from __future__ import annotations

import gzip
import hashlib
import io
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from metis import release_artifacts
from metis.release_artifacts import validate_release, verify_release_bundle, write_checksums


def write_distributions(root: Path, *, wheel_version: str = "0.5.0",
                        sdist_version: str = "0.5.0") -> Path:
    dist = root / "dist"
    dist.mkdir()
    with zipfile.ZipFile(dist / "metis_ctf-0.5.0-py3-none-any.whl", "w") as archive:
        archive.writestr("metis_ctf-0.5.0.dist-info/METADATA",
                         f"Metadata-Version: 2.1\nName: metis-ctf\nVersion: {wheel_version}\n\n")
    with tarfile.open(dist / "metis_ctf-0.5.0.tar.gz", "w:gz") as archive:
        content = f"Metadata-Version: 2.1\nName: metis-ctf\nVersion: {sdist_version}\n\n".encode()
        member = tarfile.TarInfo("metis_ctf-0.5.0/PKG-INFO")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
    return dist


def test_release_validation_accepts_matching_wheel_sdist_and_tag(tmp_path):
    artifacts = validate_release(write_distributions(tmp_path), "v0.5.0", "metis-ctf", "0.5.0")
    assert [path.suffix for path in artifacts] == [".whl", ".gz"]


def test_checksums_use_release_asset_names_and_match_archive_bytes(tmp_path):
    artifacts = validate_release(write_distributions(tmp_path), "v0.5.0", "metis-ctf", "0.5.0")
    manifest = write_checksums(artifacts)
    assert manifest.parent == artifacts[0].parent
    assert manifest.read_text().splitlines() == [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in artifacts
    ]
    assert "dist/" not in manifest.read_text()


def test_release_workflow_uses_installed_module_cli(tmp_path):
    workflow = (Path(__file__).parents[1] / ".github/workflows/release.yml").read_text()
    assert ".venv/bin/python -m metis.release_artifacts" in workflow
    assert "scripts/validate_release_artifacts.py" not in workflow
    assert "--write-checksums" in workflow
    dist = write_distributions(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "metis.release_artifacts", "--dist-dir",
         str(dist), "--tag", "v0.5.0", "--write-checksums",
         "--project-name", "metis-ctf", "--project-version", "0.5.0"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (dist / "SHA256SUMS").is_file()


def test_attestation_drill_is_main_only_and_cannot_publish():
    workflow = (Path(__file__).parents[1] / ".github/workflows/release-attestation-drill.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "contents: read" in workflow
    assert "attestations: write" in workflow and "id-token: write" in workflow
    assert ".venv/bin/python -m metis.release_artifacts" in workflow
    assert "--write-checksums" in workflow
    assert "sha256sum dist/" not in workflow
    assert "gh attestation verify" in workflow
    assert "gh release create" not in workflow
    assert "uses: actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6" in workflow


def test_release_and_drill_share_checksum_generation_path():
    workflows = Path(__file__).parents[1] / ".github/workflows"
    for name in ("release.yml", "release-attestation-drill.yml"):
        workflow = (workflows / name).read_text()
        assert workflow.count(".venv/bin/python -m metis.release_artifacts") == 1
        assert workflow.count("--write-checksums") == 1
        assert "sha256sum dist/" not in workflow


@pytest.mark.parametrize("tag,project_version", [("v0.5.1", "0.5.0"), ("0.5.0", "0.5.0"),
                                                   ("v0.5.0-rc1", "0.5.0")])
def test_release_validation_rejects_mismatched_or_nonrelease_tag(tmp_path, tag, project_version):
    with pytest.raises(ValueError, match="tag"):
        validate_release(write_distributions(tmp_path), tag, "metis-ctf", project_version)


@pytest.mark.parametrize("wheel_version,sdist_version", [("0.5.1", "0.5.0"), ("0.5.0", "0.5.1")])
def test_release_validation_rejects_distribution_metadata_mismatch(tmp_path, wheel_version, sdist_version):
    with pytest.raises(ValueError, match="metadata"):
        validate_release(write_distributions(tmp_path, wheel_version=wheel_version,
                                             sdist_version=sdist_version),
                         "v0.5.0", "metis-ctf", "0.5.0")


def test_release_validation_rejects_extra_artifacts(tmp_path):
    dist = write_distributions(tmp_path)
    (dist / "untracked.zip").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="exactly one"):
        validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0")


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "traversal", "digest", "trailing", "reordered"])
def test_offline_verification_rejects_noncanonical_bundle_manifest(tmp_path, change):
    dist = write_distributions(tmp_path)
    artifacts = validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0")
    manifest = write_checksums(artifacts)
    wheel, sdist = manifest.read_bytes().splitlines(keepends=True)
    changes = {
        "missing": sdist,
        "extra": wheel + sdist + b"0" * 64 + b"  untracked.whl\n",
        "duplicate": wheel + wheel,
        "traversal": wheel[:66] + b"../" + wheel[66:] + sdist,
        "digest": b"0" * 64 + wheel[64:] + sdist,
        "trailing": wheel + sdist + b"\n",
        "reordered": sdist + wheel,
    }
    invalid = changes[change]
    manifest.write_bytes(invalid)
    with pytest.raises(ValueError, match="does not match"):
        verify_release_bundle(artifacts[0].parent, "v0.5.0", "metis-ctf", "0.5.0")
    assert manifest.read_bytes() == invalid


def test_offline_verification_accepts_bundle_then_rejects_archive_substitution(tmp_path):
    dist = write_distributions(tmp_path)
    args = ["--dist-dir", str(dist), "--tag", "v0.5.0", "--project-name", "metis-ctf", "--project-version", "0.5.0"]
    artifacts = validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0")
    manifest = write_checksums(artifacts)
    original = manifest.read_bytes()
    command = [sys.executable, "-m", "metis.release_artifacts", *args, "--verify-checksums"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr

    with zipfile.ZipFile(artifacts[0], "a") as archive:
        archive.writestr("synthetic.py", "# same package metadata, different bytes\n")
    with pytest.raises(ValueError, match="does not match"):
        verify_release_bundle(dist, "v0.5.0", "metis-ctf", "0.5.0")
    rejected = subprocess.run(command, capture_output=True, text=True, check=False)
    assert rejected.returncode != 0
    assert "does not match" in rejected.stderr
    assert manifest.read_bytes() == original


def test_offline_verification_requires_regular_manifest(tmp_path):
    artifacts = validate_release(write_distributions(tmp_path), "v0.5.0", "metis-ctf", "0.5.0")
    with pytest.raises(OSError):
        verify_release_bundle(artifacts[0].parent, "v0.5.0", "metis-ctf", "0.5.0")
    manifest = write_checksums(artifacts)
    outside = tmp_path / "external-checksums"
    manifest.rename(outside)
    manifest.symlink_to(outside)
    with pytest.raises(OSError):
        verify_release_bundle(artifacts[0].parent, "v0.5.0", "metis-ctf", "0.5.0")



def test_offline_verification_rejects_archive_swap_after_snapshot(tmp_path, monkeypatch):
    dist = write_distributions(tmp_path)
    artifacts = validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0")
    write_checksums(artifacts)
    wheel = artifacts[0]
    replacement = tmp_path / wheel.name
    replacement.write_bytes(wheel.read_bytes())
    validate_metadata = release_artifacts._validate_metadata

    def swap_and_check(*args, **kwargs):
        replacement.replace(wheel)
        validate_metadata(*args, **kwargs)

    monkeypatch.setattr(release_artifacts, "_validate_metadata", swap_and_check)
    with pytest.raises(ValueError, match="changed during verification"):
        verify_release_bundle(dist, "v0.5.0", "metis-ctf", "0.5.0")


@pytest.mark.parametrize("member", ["wheel", "manifest"])
@pytest.mark.parametrize("kind", ["fifo", "symlink"])
def test_special_file_replacing_member_is_rejected_without_blocking(tmp_path, monkeypatch, member, kind):
    dist = write_distributions(tmp_path)
    artifacts = validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0")
    manifest = write_checksums(artifacts)
    target = artifacts[0] if member == "wheel" else manifest
    bundle_entries = release_artifacts._bundle_entries

    def swap_after_listing(*args):
        paths = bundle_entries(*args)
        target.unlink()
        if kind == "fifo":
            os.mkfifo(target)
        else:
            target.symlink_to(tmp_path / "external")
        return paths

    monkeypatch.setattr(release_artifacts, "_bundle_entries", swap_after_listing)
    error = ValueError if kind == "fifo" else OSError
    with pytest.raises(error):
        verify_release_bundle(dist, "v0.5.0", "metis-ctf", "0.5.0")


@pytest.mark.parametrize(("limit", "size", "reason"), [
    ("_MAX_ARCHIVE_BYTES", 32, "file size outside bounds"),
    ("_MAX_TAR_BYTES", 512, "decompression exceeds limit"),
    ("_MAX_METADATA_BYTES", 8, "wheel metadata exceeds limit"),
    ("_MAX_MEMBERS", 0, "wheel member count exceeds limit"),
])
def test_offline_verifier_bounds_archive_work(tmp_path, monkeypatch, limit, size, reason):
    dist = write_distributions(tmp_path)
    write_checksums(validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0"))
    monkeypatch.setattr(release_artifacts, limit, size)
    with pytest.raises(ValueError, match=reason):
        verify_release_bundle(dist, "v0.5.0", "metis-ctf", "0.5.0")


def test_offline_verifier_rejects_truncated_gzip_even_with_matching_digest(tmp_path):
    dist = write_distributions(tmp_path)
    artifacts = validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0")
    artifacts[1].write_bytes(gzip.compress(b"synthetic")[:-4])
    write_checksums(artifacts)
    with pytest.raises(ValueError, match="valid gzip"):
        verify_release_bundle(dist, "v0.5.0", "metis-ctf", "0.5.0")



def test_offline_verifier_rejects_replaced_bundle_directory(tmp_path, monkeypatch):
    dist = write_distributions(tmp_path)
    write_checksums(validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0"))
    validate_metadata = release_artifacts._validate_metadata

    def replace_directory(*args, **kwargs):
        moved = dist.rename(tmp_path / "original")
        dist.mkdir()
        for path in moved.iterdir():
            (dist / path.name).write_bytes(path.read_bytes())
        validate_metadata(*args, **kwargs)

    monkeypatch.setattr(release_artifacts, "_validate_metadata", replace_directory)
    with pytest.raises(ValueError, match="directory changed during verification"):
        verify_release_bundle(dist, "v0.5.0", "metis-ctf", "0.5.0")


def test_offline_verifier_bounds_tar_members_separately(tmp_path, monkeypatch):
    dist = write_distributions(tmp_path)
    artifacts = validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0")
    with tarfile.open(artifacts[1], mode="w:gz") as archive:
        archive.addfile(tarfile.TarInfo("first"))
        archive.addfile(tarfile.TarInfo("second"))
    write_checksums(artifacts)
    monkeypatch.setattr(release_artifacts, "_MAX_MEMBERS", 1)
    with pytest.raises(ValueError, match="sdist member count exceeds limit"):
        verify_release_bundle(dist, "v0.5.0", "metis-ctf", "0.5.0")
