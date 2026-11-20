from __future__ import annotations

import gzip
import hashlib
import io
import os
import re
import struct
import subprocess
import sys
import tarfile
import zipfile
import zlib
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
    assert "--verify-checksums" in workflow
    dist = write_distributions(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "metis.release_artifacts", "--dist-dir",
         str(dist), "--tag", "v0.5.0", "--write-checksums",
         "--project-name", "metis-ctf", "--project-version", "0.5.0"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (dist / "SHA256SUMS").is_file()


def test_release_workflow_verifies_staged_bundle_before_attestation_and_publication():
    workflow = (Path(__file__).parents[1] / ".github/workflows/release.yml").read_text()
    checksum = workflow.index("--write-checksums")
    smoke = workflow.index("- name: Install the built wheel with locked dependencies and smoke test")
    verify = workflow.index("--verify-checksums")
    attest = workflow.index("uses: actions/attest@")
    publish = workflow.index("gh release create ")
    assert checksum < smoke < verify < attest < publish

    step_start = workflow.rindex("      - name: ", 0, verify)
    step_end = workflow.find("      - name: ", verify)
    verify_step = workflow[step_start:step_end]
    assert "- name: Verify exact staged release bundle" in verify_step
    assert "--dist-dir dist --tag \"$RELEASE_TAG\"" in verify_step
    assert "--project-name \"$project_name\" --project-version \"$project_version\"" in verify_step
    assert "if:" not in verify_step
    assert "continue-on-error:" not in verify_step
    assert workflow[step_end:].startswith("      - name: Attest package archives and checksums\n")
    assert "continue-on-error:" not in workflow
    assert "always()" not in workflow


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
    checksum = workflow.index("--write-checksums")
    smoke = workflow.index("- name: Install wheel with locked dependencies and smoke test")
    verify = workflow.index("--verify-checksums")
    attest = workflow.index("uses: actions/attest@")
    assert checksum < smoke < verify < attest
    verify_step_start = workflow.rindex("      - name: ", 0, verify)
    verify_step_end = workflow.find("      - name: ", verify)
    verify_step = workflow[verify_step_start:verify_step_end]
    assert "- name: Verify exact staged release candidate" in verify_step
    assert '--dist-dir dist --tag "v$project_version"' in verify_step
    assert "--project-name \"$project_name\" --project-version \"$project_version\"" in verify_step
    assert "if:" not in verify_step
    assert workflow[verify_step_end:].startswith("      - name: Attest candidate archives and checksums\n")
    assert "continue-on-error:" not in workflow


@pytest.mark.parametrize(("workflow_file", "workflow_name"), [
    ("release.yml", "release.yml"),
    ("release-attestation-drill.yml", "release-attestation-drill.yml"),
])
def test_attestation_verification_pins_repository_workflow_source_and_runner(
    workflow_file, workflow_name,
):
    workflow = (Path(__file__).parents[1] / ".github/workflows" / workflow_file).read_text()
    command_start = workflow.index('gh attestation verify "$artifact"')
    command_end = workflow.index("done", command_start)
    command = workflow[command_start:command_end]

    assert '--repo "$GITHUB_REPOSITORY"' in command
    assert (f'--cert-identity "https://github.com/$GITHUB_REPOSITORY/.github/workflows/'
            f'{workflow_name}@$GITHUB_REF"' in command)
    assert '--cert-oidc-issuer "https://token.actions.githubusercontent.com"' in command
    assert '--source-ref "$GITHUB_REF"' in command
    assert '--source-digest "$GITHUB_SHA"' in command
    assert "--deny-self-hosted-runners" in command


@pytest.mark.parametrize(("workflow_file", "publish_command"), [
    ("release.yml", "gh release create "),
    ("release-attestation-drill.yml", None),
])
def test_attestation_verification_fails_closed_for_every_release_artifact(
    workflow_file, publish_command,
):
    workflow = (Path(__file__).parents[1] / ".github/workflows" / workflow_file).read_text()
    verify = workflow.index('gh attestation verify "$artifact"')
    step_start = workflow.rindex("      - name: ", 0, verify)
    step_end = workflow.find("      - name: ", verify)
    step = workflow[step_start:] if step_end < 0 else workflow[step_start:step_end]

    assert 'for artifact in dist/*.whl dist/*.tar.gz dist/SHA256SUMS; do' in step
    assert step.count('gh attestation verify "$artifact"') == 1
    assert "||" not in step
    assert "set +e" not in step
    assert "if gh attestation verify" not in step
    assert "continue-on-error:" not in step
    assert "--cert-identity-regex" not in step
    assert "--signer-repo" not in step
    if publish_command is not None:
        assert publish_command in step
        assert verify < workflow.index(publish_command)
    else:
        assert "gh release create " not in step


def test_release_workflow_contract_covers_attestation_permissions_and_action_pins():
    workflow = (Path(__file__).parents[1] / ".github/workflows/release.yml").read_text()

    attest_start = workflow.index("      - name: Attest package archives and checksums")
    verify_start = workflow.index("      - name: Verify package attestations before publishing")
    attest_step = workflow[attest_start:verify_start]
    assert "uses: actions/attest@" in attest_step
    assert "subject-path: 'dist/*'" in attest_step

    publish = workflow.index("gh release create ", verify_start)
    verify_step = workflow[verify_start:publish]
    assert "for artifact in dist/*.whl dist/*.tar.gz dist/SHA256SUMS; do" in verify_step
    assert 'gh attestation verify "$artifact" \\\n' in verify_step
    assert '--repo "$GITHUB_REPOSITORY"' in verify_step
    assert verify_start < publish

    top_level_permissions = workflow.split("permissions:\n", 1)[1].split("concurrency:\n", 1)[0]
    assert top_level_permissions == "  contents: read\n"
    release_job = workflow.split("  release:\n", 1)[1]
    job_permissions = release_job.split("    permissions:\n", 1)[1].split("    steps:\n", 1)[0]
    assert job_permissions == "      contents: write\n      attestations: write\n      id-token: write\n"

    action_uses = re.findall(r"(?m)^\s+uses:\s*([^\s#]+)", workflow)
    assert action_uses
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", action) for action in action_uses)


def test_release_and_drill_share_checksum_generation_path():
    workflows = Path(__file__).parents[1] / ".github/workflows"
    release = (workflows / "release.yml").read_text()
    assert release.count(".venv/bin/python -m metis.release_artifacts") == 2
    assert release.count("--write-checksums") == 1
    assert release.count("--verify-checksums") == 1
    assert "sha256sum dist/" not in release

    drill = (workflows / "release-attestation-drill.yml").read_text()
    assert drill.count(".venv/bin/python -m metis.release_artifacts") == 2
    assert drill.count("--write-checksums") == 1
    assert drill.count("--verify-checksums") == 1
    assert "sha256sum dist/" not in drill


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



def test_offline_verifier_rejects_deflated_metadata_with_forged_small_size(tmp_path):
    dist = write_distributions(tmp_path)
    artifacts = validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0")
    wheel = artifacts[0]
    metadata = b"Metadata-Version: 2.1\nName: metis-ctf\nVersion: 0.5.0\n\n"
    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metis_ctf-0.5.0.dist-info/METADATA", metadata + b"x" * (256 * 1024))
    data = bytearray(wheel.read_bytes())
    central_entry = data.index(b"PK\x01\x02")
    struct.pack_into("<I", data, central_entry + 16, zlib.crc32(metadata))
    struct.pack_into("<I", data, central_entry + 24, len(metadata))
    wheel.write_bytes(data)
    write_checksums(artifacts)

    with zipfile.ZipFile(wheel) as archive:
        assert archive.read(archive.infolist()[0]) == metadata
    with pytest.raises(ValueError, match="wheel"):
        verify_release_bundle(dist, "v0.5.0", "metis-ctf", "0.5.0")



@pytest.mark.parametrize("artifact_index", [0, 1])
def test_offline_verifier_rejects_second_metadata_candidate_before_parsing(tmp_path, monkeypatch, artifact_index):
    dist = write_distributions(tmp_path)
    artifacts = validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0")
    if artifact_index == 0:
        with zipfile.ZipFile(artifacts[0], "a") as archive:
            archive.writestr("second.dist-info/METADATA", b"must not parse")
        message = "exactly one dist-info/METADATA"
    else:
        with tarfile.open(artifacts[1], mode="w:gz") as archive:
            for location, data in [
                ("original/PKG-INFO", b"Name: metis-ctf\nVersion: 0.5.0\n\n"),
                ("second/PKG-INFO", b"must not parse"),
            ]:
                item = tarfile.TarInfo(location)
                item.size = len(data)
                archive.addfile(item, io.BytesIO(data))
        message = "exactly one PKG-INFO"
    write_checksums(artifacts)
    parse = release_artifacts.metadata_version

    def reject_unexpected_parse(data):
        assert data != b"must not parse"
        return parse(data)

    monkeypatch.setattr(release_artifacts, "metadata_version", reject_unexpected_parse)
    with pytest.raises(ValueError, match=message):
        verify_release_bundle(dist, "v0.5.0", "metis-ctf", "0.5.0")



def test_offline_verifier_rejects_recursive_tar_extensions(tmp_path):
    dist = write_distributions(tmp_path)
    artifacts = validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0")
    extension = tarfile.TarInfo("synthetic-extension")
    extension.type = tarfile.XHDTYPE
    raw_tar = extension.tobuf() * (sys.getrecursionlimit() + 200) + b"\0" * 1024
    artifacts[1].write_bytes(gzip.compress(raw_tar))
    write_checksums(artifacts)
    with pytest.raises(ValueError, match="tar extension chain"):
        verify_release_bundle(dist, "v0.5.0", "metis-ctf", "0.5.0")



def test_offline_verifier_rejects_pax_dictionary_amplification_before_tarfile(tmp_path, monkeypatch):
    dist = write_distributions(tmp_path)
    artifacts = validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0")
    global_pax = tarfile.TarInfo.create_pax_global_header({f"x{i:05}": "v" for i in range(40_000)})
    local = tarfile.TarInfo("local")
    local.type = tarfile.XHDTYPE
    with tarfile.open(artifacts[1], "r:gz") as original:
        assert original.getmember("metis_ctf-0.5.0/PKG-INFO")
    tail = gzip.decompress(artifacts[1].read_bytes())
    artifacts[1].write_bytes(gzip.compress(global_pax + local.tobuf() * 200 + tail))
    write_checksums(artifacts)

    def must_not_normalize(*args, **kwargs):
        pytest.fail("oversized PAX dictionary reached tarfile normalization")

    monkeypatch.setattr(release_artifacts, "_validate_metadata", must_not_normalize)
    with pytest.raises(ValueError, match="tar extension chain or payload exceeds limit"):
        verify_release_bundle(dist, "v0.5.0", "metis-ctf", "0.5.0")


def test_offline_verifier_accepts_setuptools_style_pax_sdist(tmp_path):
    dist = write_distributions(tmp_path)
    artifacts = validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0")
    with tarfile.open(artifacts[1], "w:gz", format=tarfile.PAX_FORMAT) as archive:
        directory = tarfile.TarInfo("metis_ctf-0.5.0")
        directory.type = tarfile.DIRTYPE
        directory.mtime = 1_700_000_000.125
        archive.addfile(directory)
        data = b"Name: metis-ctf\nVersion: 0.5.0\n\n"
        package = tarfile.TarInfo("metis_ctf-0.5.0/PKG-INFO")
        package.mtime = directory.mtime
        package.size = len(data)
        archive.addfile(package, io.BytesIO(data))
    write_checksums(artifacts)
    assert verify_release_bundle(dist, "v0.5.0", "metis-ctf", "0.5.0") == artifacts


def _pax_record(key: bytes, value: bytes) -> bytes:
    body = b" " + key + b"=" + value + b"\n"
    length = len(body) + 1
    while len(str(length)) + len(body) != length:
        length = len(str(length)) + len(body)
    return str(length).encode("ascii") + body


def _pax_header_with_nonzero_padding(kind: bytes, padding_records: bytes) -> bytes:
    declared = b"6 a=b\n"
    header = tarfile.TarInfo("pax-padding")
    header.type = kind
    header.size = len(declared)
    payload = declared + padding_records
    assert len(payload) < tarfile.BLOCKSIZE
    return header.tobuf() + payload + bytes(tarfile.BLOCKSIZE - len(payload))


@pytest.mark.parametrize("kind", [tarfile.XHDTYPE, tarfile.XGLTYPE])
def test_offline_verifier_rejects_pax_records_hidden_in_block_padding(
    tmp_path, monkeypatch, kind
):
    dist = write_distributions(tmp_path)
    artifacts = validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0")
    raw_tar = gzip.decompress(artifacts[1].read_bytes())
    hidden_records = b"".join(_pax_record(b"x", b"y") for _ in range(70))
    artifacts[1].write_bytes(gzip.compress(
        _pax_header_with_nonzero_padding(kind, hidden_records) + raw_tar
    ))
    write_checksums(artifacts)

    def must_not_normalize(*args, **kwargs):
        pytest.fail("padded PAX records reached metadata normalization")

    monkeypatch.setattr(release_artifacts, "_validate_metadata", must_not_normalize)
    with pytest.raises(ValueError, match="nonzero tar extension padding"):
        verify_release_bundle(dist, "v0.5.0", "metis-ctf", "0.5.0")


def test_offline_verifier_rejects_padded_size_override_before_tarfile(
    tmp_path, monkeypatch
):
    dist = write_distributions(tmp_path)
    artifacts = validate_release(dist, "v0.5.0", "metis-ctf", "0.5.0")
    original_tar = gzip.decompress(artifacts[1].read_bytes())
    global_pax = tarfile.TarInfo.create_pax_global_header(
        {f"x{index}": "v" for index in range(100)}
    )
    local_headers = tarfile.TarInfo("local")
    local_headers.type = tarfile.XHDTYPE
    hidden_tar = global_pax + local_headers.tobuf() * 9 + original_tar
    local_header = tarfile.TarInfo("carrier")
    local_header.type = tarfile.XHDTYPE
    local_header.size = len(b"6 a=b\n")
    header = local_header.tobuf()
    override = b"10 size=0\n"
    padding_payload = b"6 a=b\n" + override
    assert len(padding_payload) < tarfile.BLOCKSIZE
    padding = padding_payload + bytes(tarfile.BLOCKSIZE - len(padding_payload))
    carrier = tarfile.TarInfo("carrier-data")
    carrier.size = len(hidden_tar)
    raw_tar = (
        header + padding + carrier.tobuf() + hidden_tar + bytes(tarfile.BLOCKSIZE * 2)
    )
    artifacts[1].write_bytes(gzip.compress(raw_tar))
    write_checksums(artifacts)

    def must_not_normalize(*args, **kwargs):
        pytest.fail("padded size override reached metadata normalization")

    monkeypatch.setattr(release_artifacts, "_validate_metadata", must_not_normalize)
    with pytest.raises(ValueError, match="nonzero tar extension padding"):
        verify_release_bundle(dist, "v0.5.0", "metis-ctf", "0.5.0")
