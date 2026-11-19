"""Fail closed when built distributions do not match the release tag/project."""
from __future__ import annotations

import argparse
import hashlib
import re
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

VERSION_TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def metadata_version(payload: bytes) -> tuple[str, str]:
    message = BytesParser().parsebytes(payload)
    name = message.get("Name")
    version = message.get("Version")
    if not name or not version:
        raise ValueError("distribution metadata must include Name and Version")
    return name, version


def inspect_distributions(dist_dir: Path, project_name: str, expected_version: str) -> list[Path]:
    if not dist_dir.is_dir():
        raise ValueError("distribution directory is missing")
    entries = sorted(dist_dir.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise ValueError("distribution directory may contain regular files only")
    wheels = [path for path in entries if path.suffix == ".whl"]
    sdists = [path for path in entries if path.name.endswith(".tar.gz")]
    allowed = set(wheels + sdists)
    extras = [path for path in entries if path.name != "SHA256SUMS" and path not in allowed]
    if len(wheels) != 1 or len(sdists) != 1 or extras:
        raise ValueError("expected exactly one wheel and one .tar.gz sdist, with no other files")

    wheel_metadata = []
    try:
        with zipfile.ZipFile(wheels[0]) as archive:
            for zip_item in archive.infolist():
                path = PurePosixPath(zip_item.filename)
                if path.name == "METADATA" and path.parent.name.endswith(".dist-info"):
                    wheel_metadata.append(metadata_version(archive.read(zip_item)))
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("wheel is not a valid ZIP distribution") from exc
    if len(wheel_metadata) != 1:
        raise ValueError("wheel must contain exactly one dist-info/METADATA")

    sdist_metadata = []
    try:
        with tarfile.open(sdists[0], mode="r:gz") as archive:
            for tar_item in archive.getmembers():
                if PurePosixPath(tar_item.name).name == "PKG-INFO" and tar_item.isfile():
                    stream = archive.extractfile(tar_item)
                    if stream is not None:
                        sdist_metadata.append(metadata_version(stream.read()))
    except (OSError, tarfile.TarError) as exc:
        raise ValueError("sdist is not a valid gzip tar distribution") from exc
    if len(sdist_metadata) != 1:
        raise ValueError("sdist must contain exactly one PKG-INFO")

    for name, version in [*wheel_metadata, *sdist_metadata]:
        if normalized_name(name) != normalized_name(project_name) or version != expected_version:
            raise ValueError("wheel/sdist metadata does not match project name and release tag")
    if not wheels[0].stat().st_size or not sdists[0].stat().st_size:
        raise ValueError("distribution archives must not be empty")
    return wheels + sdists


def validate_release(dist_dir: Path, tag: str, project_name: str, project_version: str) -> list[Path]:
    match = VERSION_TAG.fullmatch(tag)
    if not match:
        raise ValueError("release tag must use vMAJOR.MINOR.PATCH")
    tag_version = ".".join(match.groups())
    if tag_version != project_version:
        raise ValueError("release tag version does not match pyproject.toml")
    return inspect_distributions(dist_dir, project_name, tag_version)


def _checksum_manifest(artifacts: list[Path]) -> Path:
    if not artifacts:
        raise ValueError("no release artifacts to checksum")
    manifest = artifacts[0].parent / "SHA256SUMS"
    if len(set(artifacts)) != len(artifacts):
        raise ValueError("duplicate release artifact path")
    for artifact in artifacts:
        if (artifact.parent != manifest.parent or artifact.name == manifest.name
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,254}", artifact.name) is None):
            raise ValueError("release artifacts must share a directory and have safe names")
    return manifest


def _checksum_bytes(artifacts: list[Path]) -> bytes:
    lines = []
    for artifact in artifacts:
        with artifact.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        lines.append(f"{digest}  {artifact.name}\n")
    return "".join(lines).encode("ascii")


def write_checksums(artifacts: list[Path]) -> Path:
    """Write a portable checksum manifest beside the validated archives."""
    manifest = _checksum_manifest(artifacts)
    manifest.write_bytes(_checksum_bytes(artifacts))
    return manifest


def verify_checksums(artifacts: list[Path]) -> None:
    """Compare a staged manifest with the exact validated archive set."""
    manifest = _checksum_manifest(artifacts)
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("regular SHA256SUMS manifest required")
    expected = _checksum_bytes(artifacts)
    # Filenames come from the validated bundle. Manifest contents are never
    # interpreted as paths, and the extra byte detects trailing data.
    with manifest.open("rb") as stream:
        if stream.read(len(expected) + 1) != expected:
            raise ValueError("SHA256SUMS does not match the validated release archives")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--project-version", required=True)
    checksum_mode = parser.add_mutually_exclusive_group()
    checksum_mode.add_argument("--write-checksums", action="store_true")
    checksum_mode.add_argument("--verify-checksums", action="store_true")
    args = parser.parse_args()
    try:
        artifacts = validate_release(args.dist_dir, args.tag, args.project_name, args.project_version)
        if args.write_checksums:
            write_checksums(artifacts)
        elif args.verify_checksums:
            verify_checksums(artifacts)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print("Validated release distributions:")
    for path in artifacts:
        print(path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
