"""Fail closed when built distributions do not match the release tag/project."""
from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--project-version", required=True)
    args = parser.parse_args()
    try:
        artifacts = validate_release(args.dist_dir, args.tag, args.project_name, args.project_version)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print("Validated release distributions:")
    for path in artifacts:
        print(path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
