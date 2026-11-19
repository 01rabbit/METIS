from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from metis.release_artifacts import validate_release, write_checksums


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
    assert "gh attestation verify" in workflow
    assert "gh release create" not in workflow
    assert "uses: actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6" in workflow


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
