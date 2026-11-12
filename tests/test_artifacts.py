import hashlib
import os

import pytest

from metis.core.artifacts import artifact_digest, read_artifact


def test_regular_snapshot_and_digest(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/data.txt").write_bytes(b"fixture")
    content = read_artifact(tmp_path, "nested/data.txt")
    assert content == b"fixture"
    assert artifact_digest(content) == hashlib.sha256(b"fixture").hexdigest()


@pytest.mark.parametrize("relative", ["", ".", "../secret", "/secret", "C:secret",
                                      "..\\secret", "data\x00.txt"])
def test_invalid_paths_are_denied(tmp_path, relative):
    with pytest.raises(ValueError):
        read_artifact(tmp_path, relative)


def test_symlink_file_directory_and_root_are_denied(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "oracle"
    secret.write_bytes(b"hidden")
    (root / "file").symlink_to(secret)
    (root / "dir").symlink_to(tmp_path, target_is_directory=True)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    for directory, relative in [(root, "file"), (root, "dir/oracle"), (alias, "file")]:
        with pytest.raises(OSError):
            read_artifact(directory, relative)


def test_special_files_and_oversized_artifacts_are_denied(tmp_path):
    (tmp_path / "large").write_bytes(b"12345")
    with pytest.raises(ValueError, match="bounded regular"):
        read_artifact(tmp_path, "large", max_bytes=4)
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(ValueError, match="bounded regular"):
        read_artifact(tmp_path, "pipe")
