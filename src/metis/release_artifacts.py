"""Fail closed when built distributions do not match the release tag/project."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import os
import re
import stat
import tarfile
import zipfile
import zlib
from copy import copy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import BinaryIO

VERSION_TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


_MAX_ARCHIVE_BYTES = 16 * 1024**2
_MAX_TAR_BYTES = 32 * 1024**2
_MAX_METADATA_BYTES = 128 * 1024
_MAX_MEMBERS = 4096
_MAX_RAW_TAR_HEADERS = 8192
_MAX_TAR_EXTENSION_CHAIN = 8
_MAX_TAR_EXTENSION_BYTES = 256 * 1024
_MAX_PAX_RECORDS = 64
_PAX_TYPES = frozenset((tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE))
_TAR_EXTENSION_TYPES = _PAX_TYPES | {tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK}
_MAX_MANIFEST_BYTES = 2 * (64 + 2 + 255 + 1)


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
    wheels, sdists = _distribution_paths(entries)
    _validate_metadata(wheels, sdists, project_name, expected_version)
    if not wheels.stat().st_size or not sdists.stat().st_size:
        raise ValueError("distribution archives must not be empty")
    return [wheels, sdists]


def _distribution_paths(entries: list[Path]) -> tuple[Path, Path]:
    wheels = [path for path in entries if path.suffix == ".whl"]
    sdists = [path for path in entries if path.name.endswith(".tar.gz")]
    allowed = set(wheels + sdists)
    extras = [path for path in entries if path.name != "SHA256SUMS" and path not in allowed]
    if len(wheels) != 1 or len(sdists) != 1 or extras:
        raise ValueError("expected exactly one wheel and one .tar.gz sdist, with no other files")
    return wheels[0], sdists[0]


def _validate_metadata(wheel: Path | BinaryIO, sdist: Path | BinaryIO,
                       project_name: str, expected_version: str, *, bounded: bool = False) -> None:
    wheel_metadata: list[tuple[str, str]] = []
    try:
        with zipfile.ZipFile(wheel) as archive:
            if bounded and len(archive.infolist()) > _MAX_MEMBERS:
                raise ValueError("wheel member count exceeds limit")
            for zip_item in archive.infolist():
                path = PurePosixPath(zip_item.filename)
                if path.name == "METADATA" and path.parent.name.endswith(".dist-info"):
                    if bounded and wheel_metadata:
                        raise ValueError("wheel must contain exactly one dist-info/METADATA")
                    if bounded and zip_item.file_size > _MAX_METADATA_BYTES:
                        raise ValueError("wheel metadata exceeds limit")
                    if bounded and zip_item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                        raise ValueError("unsupported wheel metadata compression")
                    item = zip_item
                    if bounded:
                        # ZipExtFile normally stops at the declared size, so a
                        # forged small size can hide an expanded suffix.
                        item = copy(zip_item)
                        item.file_size = _MAX_METADATA_BYTES + 1
                    with archive.open(item) as stream:
                        payload = stream.read(_MAX_METADATA_BYTES + 1) if bounded else stream.read()
                    if bounded and len(payload) != zip_item.file_size:
                        raise ValueError("wheel metadata size does not match ZIP directory")
                    wheel_metadata.append(metadata_version(payload))
    except (OSError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
        raise ValueError("wheel is not a valid ZIP distribution") from exc
    if len(wheel_metadata) != 1:
        raise ValueError("wheel must contain exactly one dist-info/METADATA")

    sdist_metadata: list[tuple[str, str]] = []
    try:
        with (tarfile.open(sdist, mode="r:gz") if isinstance(sdist, Path)
              else tarfile.open(fileobj=sdist, mode="r:")) as archive:
            for index, tar_item in enumerate(archive, start=1):
                if bounded and index > _MAX_MEMBERS:
                    raise ValueError("sdist member count exceeds limit")
                if PurePosixPath(tar_item.name).name == "PKG-INFO" and tar_item.isfile():
                    if bounded and sdist_metadata:
                        raise ValueError("sdist must contain exactly one PKG-INFO")
                    if bounded and tar_item.size > _MAX_METADATA_BYTES:
                        raise ValueError("sdist metadata exceeds limit")
                    metadata_stream = archive.extractfile(tar_item)
                    if metadata_stream is not None:
                        with metadata_stream:
                            sdist_metadata.append(metadata_version(metadata_stream.read()))
    except (OSError, RecursionError, tarfile.TarError) as exc:
        raise ValueError("sdist is not a valid gzip tar distribution") from exc
    if len(sdist_metadata) != 1:
        raise ValueError("sdist must contain exactly one PKG-INFO")

    for name, version in [*wheel_metadata, *sdist_metadata]:
        if normalized_name(name) != normalized_name(project_name) or version != expected_version:
            raise ValueError("wheel/sdist metadata does not match project name and release tag")


def _release_version(tag: str, project_version: str) -> str:
    match = VERSION_TAG.fullmatch(tag)
    if not match:
        raise ValueError("release tag must use vMAJOR.MINOR.PATCH")
    tag_version = ".".join(match.groups())
    if tag_version != project_version:
        raise ValueError("release tag version does not match pyproject.toml")
    return tag_version


def validate_release(dist_dir: Path, tag: str, project_name: str, project_version: str) -> list[Path]:
    return inspect_distributions(dist_dir, project_name, _release_version(tag, project_version))


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


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _snapshot(path: Path, directory_fd: int, limit: int) -> tuple[bytes, os.stat_result]:
    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("release bundle requires regular files")
        if not 0 < info.st_size <= limit:
            raise ValueError("release bundle file size outside bounds")
        data = stream.read(limit + 1)
        if len(data) != info.st_size or _file_identity(os.fstat(stream.fileno())) != _file_identity(info):
            raise ValueError("release bundle file changed while reading")
    return data, info


def _bundle_entries(dist_dir: Path, directory_fd: int) -> list[Path]:
    with os.scandir(directory_fd) as entries:
        paths = []
        for entry in entries:
            paths.append(dist_dir / entry.name)
            if len(paths) > 3:
                raise ValueError("release bundle contains extra files")
    return paths


def _pax_record_count(payload: bytes) -> int:
    offset = count = 0
    while offset < len(payload):
        split = payload.find(b" ", offset, offset + 8)
        if split == -1 or not payload[offset:split].isdigit():
            raise ValueError("invalid PAX record length")
        length = int(payload[offset:split])
        end = offset + length
        if end > len(payload) or end <= split + 3 or payload[end - 1] != 10:
            raise ValueError("invalid PAX record framing")
        key, equals, _ = payload[split + 1:end - 1].partition(b"=")
        if not key or not equals:
            raise ValueError("invalid PAX record key")
        if key == b"size" or key.startswith(b"GNU.sparse."):
            raise ValueError("PAX size overrides and sparse tar encodings are unsupported")
        count += 1
        if count > _MAX_PAX_RECORDS:
            raise ValueError("PAX record count exceeds limit")
        offset = end
    return count


def _check_raw_tar(data: bytes) -> None:
    # Walk physical headers before tarfile can resolve extension chains or
    # recursively copy inherited global PAX dictionaries.
    offset = headers = chain = extension_bytes = global_records = 0
    block = tarfile.BLOCKSIZE
    while offset + block <= len(data):
        header = data[offset:offset + block]
        if header == bytes(block):
            if chain:
                raise ValueError("tar extension chain has no member")
            return
        headers += 1
        if headers > _MAX_RAW_TAR_HEADERS:
            raise ValueError("raw tar header count exceeds limit")
        try:
            member = tarfile.TarInfo.frombuf(header, "utf-8", "surrogateescape")
        except tarfile.HeaderError as exc:
            raise ValueError("invalid tar header") from exc
        if member.size < 0 or member.type == tarfile.GNUTYPE_SPARSE:
            raise ValueError("negative size or sparse tar encodings are unsupported")
        payload_start = offset + block
        offset = payload_start + ((member.size + block - 1) // block) * block
        if offset > len(data):
            raise ValueError("truncated tar member")
        if member.type in _TAR_EXTENSION_TYPES:
            chain += 1
            extension_bytes += member.size
            if chain > _MAX_TAR_EXTENSION_CHAIN or extension_bytes > _MAX_TAR_EXTENSION_BYTES:
                raise ValueError("tar extension chain or payload exceeds limit")
            if member.type in _PAX_TYPES:
                records = _pax_record_count(data[payload_start:payload_start + member.size])
                if member.type == tarfile.XGLTYPE:
                    global_records += records
                    if global_records > _MAX_PAX_RECORDS:
                        raise ValueError("global PAX record count exceeds limit")
        else:
            if member.size and not member.isreg() and member.type in tarfile.SUPPORTED_TYPES:
                raise ValueError("tar member type has unexpected payload")
            chain = 0
    raise ValueError("missing tar end marker")


def verify_release_bundle(dist_dir: Path, tag: str, project_name: str, project_version: str) -> list[Path]:
    """Verify bounded, immutable copies of the exact staged bundle members."""
    expected_version = _release_version(tag, project_version)
    directory_fd = os.open(dist_dir, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    try:
        before = os.fstat(directory_fd)
        artifacts = list(_distribution_paths(_bundle_entries(dist_dir, directory_fd)))
        manifest = _checksum_manifest(artifacts)
        wheel, wheel_info = _snapshot(artifacts[0], directory_fd, _MAX_ARCHIVE_BYTES)
        sdist, sdist_info = _snapshot(artifacts[1], directory_fd, _MAX_ARCHIVE_BYTES)
        recorded, manifest_info = _snapshot(manifest, directory_fd, _MAX_MANIFEST_BYTES)
        expected = "".join(
            f"{hashlib.sha256(data).hexdigest()}  {path.name}\n"
            for path, data in zip(artifacts, (wheel, sdist), strict=True)
        ).encode("ascii")
        if recorded != expected:
            raise ValueError("SHA256SUMS does not match the validated release archives")
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(sdist)) as stream:
                tar = stream.read(_MAX_TAR_BYTES + 1)
        except (EOFError, OSError, zlib.error) as exc:
            raise ValueError("sdist is not a valid gzip distribution") from exc
        if len(tar) > _MAX_TAR_BYTES:
            raise ValueError("sdist decompression exceeds limit")
        _check_raw_tar(tar)
        _validate_metadata(io.BytesIO(wheel), io.BytesIO(tar), project_name, expected_version, bounded=True)

        for path, info in zip([*artifacts, manifest], (wheel_info, sdist_info, manifest_info), strict=True):
            after = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
            if _file_identity(after) != _file_identity(info):
                raise ValueError("release bundle file changed during verification")
        if _file_identity(dist_dir.lstat()) != _file_identity(before):
            raise ValueError("release bundle directory changed during verification")
        return artifacts
    finally:
        os.close(directory_fd)


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
        if args.verify_checksums:
            artifacts = verify_release_bundle(args.dist_dir, args.tag, args.project_name, args.project_version)
        else:
            artifacts = validate_release(args.dist_dir, args.tag, args.project_name, args.project_version)
            if args.write_checksums:
                write_checksums(artifacts)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print("Validated release distributions:")
    for path in artifacts:
        print(path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
