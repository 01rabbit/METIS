import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from metis.core.codex_session import (
    MAX_ADDED_ARTIFACT_NAME,
    MAX_ADDED_ARTIFACTS_PER_RUN,
    MAX_DERIVED_ARTIFACTS_PER_RUN,
    CodexSession,
    DerivedArtifactLimitError,
    transform,
)
from metis.core.contracts import ChallengeManifest, RunStatus
from metis.core.runtime import ToolRequest


def test_codex_native_demo_without_api_or_docker(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("METIS_OPENAI_API_KEY", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("native tools must not start any process")

    monkeypatch.setattr(subprocess, "run", forbidden)
    database = tmp_path / "sessions.sqlite"
    session = CodexSession(database)
    for context in session.demo():
        description = context["challenge"]["description"]
        payload = description.rsplit(": ", 1)[1]
        tool = "base64_decode" if "base64" in description else "hex_decode"
        run_id = context["run_id"]
        result = session.act(run_id, ToolRequest(tool=tool, data=payload))
        assert result["ok"]
        answer = result["output"]
        assert not session.submit(run_id, "METIS{wrong}")["verified"]
        assert session.submit(run_id, answer)["verified"]
        assert session.context(run_id)["status"] == "solved"
        assert answer not in session.store.export_jsonl(run_id)
        assert answer.encode() not in database.read_bytes()
        with pytest.raises(ValueError, match="not awaiting"):
            session.act(run_id, ToolRequest(tool=tool, data=payload))


def test_native_scope_budget_and_unverified_candidate(tmp_path):
    session = CodexSession(tmp_path / "sessions.sqlite")
    manifest = ChallengeManifest.model_validate({
        "challenge_id": "local", "title": "Local", "description": "Solve local data",
        "scope": {"authorized": True, "granted_by": "test", "challenge_id": "local"},
    })
    context = session.start(manifest, max_actions=1)
    assert not session.submit(context["run_id"], "anything")["verified"]
    with pytest.raises(ValueError, match="budget exhausted"):
        session.act(context["run_id"], ToolRequest(tool="sha256", data="x"))
    assert session.context(context["run_id"])["status"] == "exhausted"
    cancelled = session.start(manifest)
    assert session.cancel(cancelled["run_id"])["status"] == "cancelled"
    bad = manifest.model_dump()
    bad["scope"]["allowed_endpoints"] = [{"hostname": "localhost", "port": 80}]
    scoped = session.start(ChallengeManifest.model_validate(bad))
    assert scoped["challenge"]["scope"]["allowed_endpoints"]
    assert scoped["network_tools"] == []


def test_native_invalid_inputs_cannot_be_executed():
    assert not transform(ToolRequest(tool="shell", data="touch /tmp/not-allowed")).ok
    assert not transform(ToolRequest(tool="hex_decode", data="!bad")).ok
    assert not transform(ToolRequest(tool="sha256", data="あ" * 30_000)).ok
    assert transform(ToolRequest(tool="sha256", data="fixture")).output == hashlib.sha256(
        b"fixture",
    ).hexdigest()


@pytest.mark.parametrize(("tool", "result", "expected", "forbidden"), [
    ("infozip_seed", {
        "found": True, "generator": "glibc", "salt": "pid", "seed": 987654321,
        "members": 7, "matched_leaked_bytes": 7, "tried_seeds": 10,
        "seconds": 0.9, "random_header_bytes": ["deadbeef"], "next": "private detail",
    }, {"found": "True", "generator": "glibc", "salt": "pid", "members": "7",
        "matched_leaked_bytes": "7"}, ("987654321", "deadbeef", "private detail")),
    ("zipcrypto_decrypt", {
        "name": "secret-name", "size": 12, "crc_ok": True,
        "stay_header_ok": True, "plaintext": b"private-plaintext", "base64": "private-base64",
    }, {"crc_ok": "True", "plaintext_bytes": "12", "stay_header_ok": "True"},
     ("secret-name", "private-plaintext", "private-base64")),
    ("zipcrypto_stay_scan", {
        "next_index": 99, "complete": False, "scanned": 99, "hits_count": 2,
        "candidate_shard": ".metis-state/private-stay/secret-shard.json",
        "hits": [[4242424242, [1, 2, 3, 4, 5, 6, 7]]],
    }, {"next_index": "99", "complete": "False", "scanned": "99", "hits_count": "2"},
     ("secret-shard.json", "4242424242", "private-stay")),
    ("text", {"text": "arbitrary-private-output"}, {}, ("arbitrary-private-output",)),
])
def test_artifact_evidence_records_safe_facts_only(tmp_path, monkeypatch, tool, result, expected, forbidden):
    source = tmp_path / "source.bin"
    source.write_bytes(b"fixture")
    session = CodexSession(tmp_path / "sessions.sqlite")
    run_id = session.intake(title="privacy", description="fixture", paths=[source])["run_id"]

    monkeypatch.setattr("metis.core.codex_session.inspect_file", lambda *args, **kwargs: result)
    observed = session.artifact(run_id, "00-source.bin", tool)
    assert observed["ok"] is True
    event = session.store.read(run_id)[observed["_evidence_sequence"]]
    assert event.detail["tool_ok"] == "true"
    assert event.detail["artifact_tool"] == tool
    for key, value in expected.items():
        assert event.detail[key] == value
    serialized = session.store.export_jsonl(run_id) + session.database.read_bytes().decode("latin1")
    for secret in forbidden:
        assert secret not in serialized


def test_purge_derived_keeps_original_and_user_added_artifacts(tmp_path):
    database = tmp_path / "sessions.sqlite"
    original = tmp_path / "original.txt"
    added = tmp_path / "added.txt"
    original.write_bytes(b"user supplied original")
    added.write_bytes(b"user added later")
    session = CodexSession(database)
    run_id = session.intake(title="retention", description="local fixture", paths=[original])["run_id"]
    derived = session.store_artifact(run_id, b"generated intermediate")
    added_relative = session.add_file(run_id, added)["artifact"]
    session._emit(run_id, RunStatus.CANCELLED)
    root = session.artifact_root(run_id)
    assert root is not None
    derived_file = root / derived
    before_manifest = session._session(run_id)[0]

    preview = session.purge_derived(run_id)
    assert preview["applied"] is False
    assert preview["files"] == [{"path": derived, "state": "present", "size": 22}]
    assert session._session(run_id)[0] == before_manifest
    assert derived_file.read_bytes() == b"generated intermediate"

    result = session.purge_derived(run_id, apply=True)
    assert result["applied"] is True
    assert result["manifest_entries_removed"] == 1
    assert result["files"] == [{"path": derived, "state": "deleted", "size": 22}]
    assert not derived_file.exists()
    challenge = session.context(run_id)["challenge"]
    assert challenge["artifacts"] == ["00-original.txt", added_relative]
    assert (root / "00-original.txt").read_bytes() == b"user supplied original"
    assert (root / added_relative).read_bytes() == b"user added later"

    repeated = session.purge_derived(run_id, apply=True)
    assert repeated["files"] == []
    assert repeated["manifest_entries_removed"] == 0


def test_purge_added_preview_and_apply_preserve_original_and_derived_artifacts(tmp_path):
    database = tmp_path / "sessions.sqlite"
    original = tmp_path / "original.txt"
    added = tmp_path / "download.txt"
    original.write_bytes(b"original challenge input")
    added.write_bytes(b"operator download")
    session = CodexSession(database)
    run_id = session.intake(title="added-retention", description="local fixture", paths=[original])["run_id"]
    derived = session.store_artifact(run_id, b"generated intermediate")
    added_relative = session.add_file(run_id, added)["artifact"]
    session._emit(run_id, RunStatus.CANCELLED)
    root = session.artifact_root(run_id)
    assert root is not None
    added_file = root / added_relative
    derived_file = root / derived
    before_manifest = session._session(run_id)[0]

    preview = session.purge_added(run_id)
    assert preview["applied"] is False
    assert preview["files"] == [{"path": added_relative, "state": "present", "size": 17}]
    assert session._session(run_id)[0] == before_manifest
    assert added_file.read_bytes() == b"operator download"

    result = session.purge_added(run_id, apply=True)
    assert result["applied"] is True
    assert result["manifest_entries_removed"] == 1
    assert result["files"] == [{"path": added_relative, "state": "deleted", "size": 17}]
    assert not added_file.exists()
    assert derived_file.read_bytes() == b"generated intermediate"
    assert session.context(run_id)["challenge"]["artifacts"] == ["00-original.txt", derived]
    assert (root / "00-original.txt").read_bytes() == b"original challenge input"

    repeated = session.purge_added(run_id, apply=True)
    assert repeated["files"] == []
    assert repeated["manifest_entries_removed"] == 0


def test_purge_added_recovers_after_file_unlink_before_manifest_update(tmp_path):
    source = tmp_path / "download.bin"
    source.write_bytes(b"download")
    session = CodexSession(tmp_path / "sessions.sqlite")
    run_id = session.intake(title="retry-added", description="fixture", paths=[source])["run_id"]
    added = session.add_file(run_id, source)["artifact"]
    session._emit(run_id, RunStatus.CANCELLED)
    root = session.artifact_root(run_id)
    assert root is not None
    (root / added).unlink()

    result = session.purge_added(run_id, apply=True)
    assert result["files"] == [{"path": added, "state": "missing", "size": 0}]
    assert result["manifest_entries_removed"] == 1
    assert added not in session.context(run_id)["challenge"]["artifacts"]


def test_purge_added_rejects_symlinks_and_unregistered_entries(tmp_path):
    database = tmp_path / "sessions.sqlite"
    source = tmp_path / "download.txt"
    external = tmp_path / "outside.txt"
    source.write_text("download")
    external.write_text("must remain")
    session = CodexSession(database)
    run_id = session.intake(title="added-symlink", description="fixture", paths=[source])["run_id"]
    added = session.add_file(run_id, source)["artifact"]
    session._emit(run_id, RunStatus.CANCELLED)
    root = session.artifact_root(run_id)
    assert root is not None
    target = root / added
    target.unlink()
    target.symlink_to(external)
    with pytest.raises(ValueError, match="added artifact is not a private regular file"):
        session.purge_added(run_id, apply=True)
    assert external.read_text() == "must remain"

    target.unlink()
    target.write_text("download")
    unregistered = root / ".metis-added" / "unregistered.txt"
    unregistered.write_text("leave untouched")
    with pytest.raises(ValueError, match="added directory contains unregistered entries"):
        session.purge_added(run_id, apply=True)
    assert target.read_text() == "download"
    assert unregistered.read_text() == "leave untouched"


def test_add_file_and_added_purge_enforce_bounded_entries(tmp_path, monkeypatch):
    database = tmp_path / "sessions.sqlite"
    source = tmp_path / "download.bin"
    source.write_bytes(b"download")
    session = CodexSession(database)
    run_id = session.intake(title="added-cap", description="fixture", paths=[source])["run_id"]
    added = [session.add_file(run_id, source)["artifact"]
             for _ in range(MAX_ADDED_ARTIFACTS_PER_RUN)]
    with pytest.raises(ValueError, match="added artifact count exceeds per-run limit"):
        session.add_file(run_id, source)
    root = session.artifact_root(run_id)
    assert root is not None
    folder = root / ".metis-added"
    for index in range(MAX_ADDED_ARTIFACTS_PER_RUN + 1):
        (folder / f"unregistered-{index:03d}.bin").write_bytes(b"leave")
    session._emit(run_id, RunStatus.CANCELLED)
    original_scandir = os.scandir
    examined = 0

    @contextmanager
    def counted_scandir(directory):
        with original_scandir(directory) as entries:
            def observed_entries():
                nonlocal examined
                for entry in entries:
                    examined += 1
                    yield entry
            yield observed_entries()

    monkeypatch.setattr(os, "scandir", counted_scandir)
    with pytest.raises(ValueError, match="added directory"):
        session.purge_added(run_id, apply=True)
    assert 1 <= examined <= MAX_ADDED_ARTIFACTS_PER_RUN + 1
    assert all((root / path).is_file() for path in added)


def test_add_file_stops_after_bounded_name_collisions(tmp_path):
    source = tmp_path / "same.txt"
    source.write_text("download")
    session = CodexSession(tmp_path / "sessions.sqlite")
    run_id = session.intake(title="collision-cap", description="fixture", paths=[source])["run_id"]
    root = session.artifact_root(run_id)
    assert root is not None
    folder = root / ".metis-added"
    folder.mkdir(mode=0o700)
    for index in range(1, MAX_ADDED_ARTIFACTS_PER_RUN + 2):
        name = "same.txt" if index == 1 else f"same-{index}.txt"
        (folder / name).write_text("collision")

    with pytest.raises(ValueError, match="collision limit"):
        session.add_file(run_id, source)


def test_add_file_refuses_symlinked_added_directory(tmp_path):
    source = tmp_path / "download.txt"
    source.write_text("download")
    external = tmp_path / "external"
    external.mkdir()
    session = CodexSession(tmp_path / "sessions.sqlite")
    run_id = session.intake(title="symlinked-added-dir", description="fixture", paths=[source])["run_id"]
    root = session.artifact_root(run_id)
    assert root is not None
    (root / ".metis-added").symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="invalid snapshot directory"):
        session.add_file(run_id, source)
    assert list(external.iterdir()) == []


def test_added_purge_accepts_collision_name_at_maximum_length(tmp_path):
    source = tmp_path / ("x." + "a" * 58)
    source.write_text("download")
    session = CodexSession(tmp_path / "sessions.sqlite")
    run_id = session.intake(title="long-collision", description="fixture", paths=[source])["run_id"]
    added = [session.add_file(run_id, source)["artifact"]
             for _ in range(MAX_ADDED_ARTIFACTS_PER_RUN)]
    assert len({path.removeprefix(".metis-added/") for path in added}) == MAX_ADDED_ARTIFACTS_PER_RUN
    assert all(len(path.removeprefix(".metis-added/")) <= MAX_ADDED_ARTIFACT_NAME
               for path in added)
    session._emit(run_id, RunStatus.CANCELLED)

    preview = session.purge_added(run_id)
    assert preview["applied"] is False
    assert len(preview["files"]) == MAX_ADDED_ARTIFACTS_PER_RUN
    applied = session.purge_added(run_id, apply=True)
    assert applied["applied"] is True
    assert len(applied["files"]) == MAX_ADDED_ARTIFACTS_PER_RUN
    assert all(item["state"] == "deleted" for item in applied["files"])


def test_added_purge_accepts_legacy_overlong_collision_name(tmp_path):
    source = tmp_path / ("a" * 56 + ".bin")
    source.write_text("download")
    session = CodexSession(tmp_path / "sessions.sqlite")
    run_id = session.intake(title="legacy-collision", description="fixture", paths=[source])["run_id"]
    added = session.add_file(run_id, source)["artifact"]
    root = session.artifact_root(run_id)
    assert root is not None
    old_name = "a" * 56 + "-12345678901234567890.bin"
    (root / added).rename(root / ".metis-added" / old_name)
    manifest = ChallengeManifest.model_validate_json(session._session(run_id)[0])
    old_data = manifest.model_dump()
    old_data["artifacts"] = [".metis-added/" + old_name]
    updated = ChallengeManifest.model_validate(old_data)
    with sqlite3.connect(session.database) as db:
        db.execute("UPDATE codex_sessions SET manifest=? WHERE run_id=?",
                   (updated.model_dump_json(), run_id))
    session._emit(run_id, RunStatus.CANCELLED)

    result = session.purge_added(run_id, apply=True)
    assert result["files"] == [{"path": ".metis-added/" + old_name,
                                "state": "deleted", "size": len("download")}]


def test_added_collision_preserves_short_extension(tmp_path):
    source = tmp_path / "challenge.zip"
    source.write_bytes(b"archive")
    session = CodexSession(tmp_path / "sessions.sqlite")
    run_id = session.intake(title="extension-collision", description="fixture", paths=[source])["run_id"]

    first = session.add_file(run_id, source)["artifact"]
    second = session.add_file(run_id, source)["artifact"]

    assert first == ".metis-added/challenge.zip"
    assert second == ".metis-added/challenge-2.zip"


@pytest.mark.parametrize(
    ("source_name", "expected_suffix"),
    [
        ("A" * 80 + ".pcap", ".pcap"),
        ("あ" * 70 + ".txt", ".txt"),
        ("x" * 55 + ".tar.gz", ".gz"),
        ("ab.c" + "d" * 70, ""),
    ],
)
def test_added_filename_bounds_and_preserves_valid_short_extension(
    tmp_path, source_name, expected_suffix,
):
    source = tmp_path / source_name
    source.write_bytes(b"fixture")
    session = CodexSession(tmp_path / "sessions.sqlite")
    run_id = session.intake(title="bounded-name", description="fixture", paths=[source])["run_id"]

    added = [session.add_file(run_id, source)["artifact"] for _ in range(2)]
    names = [item.removeprefix(".metis-added/") for item in added]
    assert all(len(name) <= MAX_ADDED_ARTIFACT_NAME for name in names)
    assert all(len(os.fsencode(name)) <= 255 for name in names)
    if expected_suffix:
        assert all(name.endswith(expected_suffix) for name in names)
    else:
        assert names[1].endswith("-2")
    assert len(set(names)) == 2


def test_store_artifact_caps_derived_entries_and_keeps_purge_recoverable(tmp_path):
    database = tmp_path / "sessions.sqlite"
    source = tmp_path / "source.txt"
    source.write_text("fixture")
    session = CodexSession(database)
    run_id = session.intake(title="derived-cap", description="fixture", paths=[source])["run_id"]
    derived = [session.store_artifact(run_id, b"generated")
               for _ in range(MAX_DERIVED_ARTIFACTS_PER_RUN)]
    other = session.store_artifact(run_id, b"other", directory_name=".metis-other")
    with pytest.raises(DerivedArtifactLimitError) as error:
        session.store_artifact(run_id, b"one too many")
    assert error.value.count == MAX_DERIVED_ARTIFACTS_PER_RUN + 1

    root = session.artifact_root(run_id)
    assert root is not None
    assert len(list((root / ".metis-derived").iterdir())) == MAX_DERIVED_ARTIFACTS_PER_RUN
    manifest = session.context(run_id)["challenge"]["artifacts"]
    assert sum(path.startswith(".metis-derived/") for path in manifest) == 100
    assert other in manifest

    session._emit(run_id, RunStatus.CANCELLED)
    result = session.purge_derived(run_id, apply=True)
    assert len(result["files"]) == MAX_DERIVED_ARTIFACTS_PER_RUN
    assert all(not (root / path).exists() for path in derived)
    assert (root / other).read_bytes() == b"other"
    assert session.context(run_id)["challenge"]["artifacts"] == ["00-source.txt", other]


def test_concurrent_derived_stores_serialize_at_per_run_cap(tmp_path):
    database = tmp_path / "sessions.sqlite"
    source = tmp_path / "source.txt"
    source.write_text("fixture")
    session = CodexSession(database)
    run_id = session.intake(title="concurrent-cap", description="fixture", paths=[source])["run_id"]
    for _ in range(MAX_DERIVED_ARTIFACTS_PER_RUN - 1):
        session.store_artifact(run_id, b"generated")

    def attempt_store(index):
        try:
            return session.store_artifact(run_id, f"writer-{index}".encode())
        except DerivedArtifactLimitError:
            return "limit"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt_store, range(2)))
    assert outcomes.count("limit") == 1
    assert sum(outcome != "limit" for outcome in outcomes) == 1
    manifest = session.context(run_id)["challenge"]["artifacts"]
    assert sum(path.startswith(".metis-derived/") for path in manifest) == 100
    root = session.artifact_root(run_id)
    assert root is not None
    assert len(list((root / ".metis-derived").iterdir())) == 100


def test_purge_derived_refuses_active_runs_and_registered_workers(tmp_path):
    database = tmp_path / "sessions.sqlite"
    source = tmp_path / "source.txt"
    source.write_text("fixture")
    session = CodexSession(database)
    active_run = session.intake(title="active", description="fixture", paths=[source])["run_id"]
    active_artifact = session.store_artifact(active_run, b"keep")
    active_root = session.artifact_root(active_run)
    assert active_root is not None
    session._emit(active_run, RunStatus.EXECUTING)
    with pytest.raises(ValueError, match="terminal"):
        session.purge_derived(active_run, apply=True)
    with pytest.raises(ValueError, match="terminal"):
        session.purge_added(active_run, apply=True)
    assert (active_root / active_artifact).exists()

    worker_run = session.intake(title="worker", description="fixture", paths=[source])["run_id"]
    worker_artifact = session.store_artifact(worker_run, b"keep")
    session._emit(worker_run, RunStatus.CANCELLED)
    worker_root = session.artifact_root(worker_run)
    assert worker_root is not None
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE sandbox_workers (run_id TEXT, engine TEXT, container_name TEXT, started REAL)")
        db.execute("INSERT INTO sandbox_workers VALUES (?, 'docker', 'test-worker', 1.0)", (worker_run,))
    with pytest.raises(ValueError, match="active operations or workers"):
        session.purge_derived(worker_run, apply=True)
    with pytest.raises(ValueError, match="active operations or workers"):
        session.purge_added(worker_run, apply=True)
    assert (worker_root / worker_artifact).exists()

    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM sandbox_workers WHERE run_id=?", (worker_run,))
        db.execute("CREATE TABLE agent_jobs (run_id TEXT, state TEXT)")
        db.execute("INSERT INTO agent_jobs VALUES (?, 'queued')", (worker_run,))
    with pytest.raises(ValueError, match="active operations or workers"):
        session.purge_derived(worker_run, apply=True)
    assert (worker_root / worker_artifact).exists()


def test_purge_derived_rejects_symlink_and_preserves_external_target(tmp_path):
    database = tmp_path / "sessions.sqlite"
    source = tmp_path / "source.txt"
    external = tmp_path / "outside.txt"
    source.write_text("fixture")
    external.write_text("must remain")
    session = CodexSession(database)
    run_id = session.intake(title="symlink", description="fixture", paths=[source])["run_id"]
    derived = session.store_artifact(run_id, b"generated")
    session._emit(run_id, RunStatus.CANCELLED)
    root = session.artifact_root(run_id)
    assert root is not None
    link = root / derived
    link.unlink()
    link.symlink_to(external)

    with pytest.raises(ValueError, match="private regular file"):
        session.purge_derived(run_id, apply=True)
    assert external.read_text() == "must remain"
    assert link.is_symlink()


def test_purge_derived_recovers_after_file_unlink_before_manifest_update(tmp_path):
    database = tmp_path / "sessions.sqlite"
    source = tmp_path / "source.txt"
    source.write_text("fixture")
    session = CodexSession(database)
    run_id = session.intake(title="retry", description="fixture", paths=[source])["run_id"]
    derived = session.store_artifact(run_id, b"generated")
    session._emit(run_id, RunStatus.CANCELLED)
    root = session.artifact_root(run_id)
    assert root is not None
    (root / derived).unlink()  # Simulate a crash after unlink and before manifest commit.

    result = session.purge_derived(run_id, apply=True)
    assert result["files"] == [{"path": derived, "state": "missing", "size": 0}]
    assert result["manifest_entries_removed"] == 1
    assert not any(path.startswith(".metis-derived/")
                   for path in session.context(run_id)["challenge"]["artifacts"])


def test_purge_derived_rejects_unregistered_directory_entries(tmp_path):
    database = tmp_path / "sessions.sqlite"
    source = tmp_path / "source.txt"
    source.write_text("fixture")
    session = CodexSession(database)
    run_id = session.intake(title="unexpected", description="fixture", paths=[source])["run_id"]
    derived = session.store_artifact(run_id, b"registered")
    session._emit(run_id, RunStatus.CANCELLED)
    root = session.artifact_root(run_id)
    assert root is not None
    registered = root / derived
    unexpected = root / ".metis-derived" / "unregistered.txt"
    unexpected.write_text("leave untouched")

    with pytest.raises(ValueError, match="unregistered entries"):
        session.purge_derived(run_id, apply=True)
    assert registered.read_bytes() == b"registered"
    assert unexpected.read_text() == "leave untouched"


def test_purge_derived_bounds_directory_scan_before_unlink(tmp_path, monkeypatch):
    database = tmp_path / "sessions.sqlite"
    source = tmp_path / "source.txt"
    source.write_text("fixture")
    session = CodexSession(database)
    run_id = session.intake(title="overfull", description="fixture", paths=[source])["run_id"]
    registered = [session.store_artifact(run_id, b"generated")
                  for _ in range(MAX_DERIVED_ARTIFACTS_PER_RUN)]
    session._emit(run_id, RunStatus.CANCELLED)
    root = session.artifact_root(run_id)
    assert root is not None
    derived_dir = root / ".metis-derived"
    for index in range(MAX_DERIVED_ARTIFACTS_PER_RUN + 1):
        (derived_dir / f"unregistered-{index:03d}.bin").write_bytes(b"leave")

    original_scandir = os.scandir
    examined = 0

    @contextmanager
    def counted_scandir(directory):
        with original_scandir(directory) as entries:
            def observed_entries():
                nonlocal examined
                for entry in entries:
                    examined += 1
                    yield entry
            yield observed_entries()

    monkeypatch.setattr(os, "scandir", counted_scandir)
    with pytest.raises(ValueError, match="derived directory"):
        session.purge_derived(run_id, apply=True)

    assert 1 <= examined <= MAX_DERIVED_ARTIFACTS_PER_RUN + 1
    assert all((root / path).is_file() for path in registered)
    assert len(list(derived_dir.glob("unregistered-*.bin"))) == MAX_DERIVED_ARTIFACTS_PER_RUN + 1


def test_codex_cli_across_processes(tmp_path):
    command = [sys.executable, "-m", "metis.cli", "codex", "--database",
               str(tmp_path / "session.sqlite")]
    demo = subprocess.run([*command, "demo"], capture_output=True, text=True, check=True)
    context = json.loads(demo.stdout)["sessions"][0]
    payload = context["challenge"]["description"].rsplit(": ", 1)[1]
    action = subprocess.run([*command, "act", context["run_id"], "base64_decode"],
                            input=payload, capture_output=True, text=True, check=True)
    answer = json.loads(action.stdout)["output"]
    result = subprocess.run([*command, "submit", context["run_id"]], input=answer,
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["verified"]


def test_recovery_preserves_budget_and_never_fabricates_verification(tmp_path):
    session = CodexSession(tmp_path / "session.sqlite")
    context = session.demo()[0]
    run_id = context["run_id"]
    session._reserve(run_id, "native_data_transform")
    assert session.context(run_id)["status"] == "executing"
    restored = CodexSession(tmp_path / "session.sqlite")
    recovered = restored.recover(run_id)
    assert recovered["status"] == "planning"
    assert recovered["actions_remaining"] == 39
    assert not any(event.status == RunStatus.SOLVED for event in restored.store.read(run_id))
    assert any(row["run_id"] == run_id for row in restored.board())
    restored._reserve(run_id, "native_data_transform")
    assert restored.cancel(run_id)["status"] == "cancelled"
    assert restored.recover(run_id)["status"] == "cancelled"


def test_emergency_stop_survives_controller_restart_without_resuming_work(tmp_path):
    database = tmp_path / "session.sqlite"
    controller = CodexSession(database)
    run_id = controller.demo()[0]["run_id"]
    command = [sys.executable, "-m", "metis.cli", "codex", "--database", str(database)]

    # Model an operation reserved by the controller when the operator stops it.
    controller._reserve(run_id, "native_data_transform")
    before_stop = controller.context(run_id)
    assert before_stop["status"] == "executing"
    assert before_stop["actions_remaining"] == 39

    stopped = json.loads(subprocess.run(
        [*command, "cancel", run_id], capture_output=True, text=True, check=True, timeout=15,
    ).stdout)
    assert stopped["status"] == "cancelled"
    stopped_events = controller.store.read(run_id)
    assert not any(event.status == RunStatus.SOLVED for event in stopped_events)

    for _ in range(2):
        recovered = json.loads(subprocess.run(
            [*command, "recover", run_id], capture_output=True, text=True, check=True, timeout=15,
        ).stdout)
        assert recovered["status"] == "cancelled"
        assert recovered["actions_remaining"] == 39
        assert recovered["worker_teardown"]["status"] == "not_running"
        assert controller.store.read(run_id) == stopped_events


def test_recovery_refuses_to_resume_when_sandbox_teardown_is_unknown(tmp_path, monkeypatch):
    database = tmp_path / "session.sqlite"
    session = CodexSession(database)
    run_id = session.demo()[0]["run_id"]
    session._reserve(run_id, "sandboxed_dynamic_execution")
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE sandbox_workers (run_id TEXT PRIMARY KEY, engine TEXT NOT NULL, "
                   "container_name TEXT NOT NULL, started REAL NOT NULL)")
        db.execute("INSERT INTO sandbox_workers VALUES (?, 'docker', 'metis-sandbox-unknown', 1)", (run_id,))
    monkeypatch.setattr("metis.core.ctf_sandbox._remove_container",
                        lambda *_: {"status": "unknown", "reason": "engine unavailable"})

    with pytest.raises(RuntimeError, match="teardown is unknown"):
        CodexSession(database).recover(run_id)
    assert session.context(run_id)["status"] == "executing"
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT container_name FROM sandbox_workers WHERE run_id=?", (run_id,)).fetchone()


def test_intake_accepts_explicit_path_through_symlinked_directory(tmp_path):
    # macOS exposes /tmp as a symlink to /private/tmp.
    real = tmp_path / "private-tmp"
    real.mkdir()
    (real / "hello.sh").write_text("#!/bin/sh\necho hi\n")
    link = tmp_path / "tmp"
    link.symlink_to(real, target_is_directory=True)
    session = CodexSession(tmp_path / "state" / "metis.sqlite")
    context = session.intake(title="t", description="d", paths=[link / "hello.sh"])
    assert context["challenge"]["artifacts"] == ["00-hello.sh"]
    fifo = real / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(ValueError):
        session.intake(title="t", description="d", paths=[link / "pipe"])


def test_wall_clock_starts_at_first_action_and_extend_resumes(tmp_path, monkeypatch):
    import time as time_module
    session = CodexSession(tmp_path / "state" / "metis.sqlite")
    note = tmp_path / "n.txt"
    note.write_text("x")
    run_id = session.intake(title="t", description="d", paths=[note], wall_seconds=60)["run_id"]
    base = time_module.time()
    monkeypatch.setattr("metis.core.codex_session.time.time", lambda: base + 3600)
    # An hour after intake with no action taken, the full budget is still available.
    context = session.context(run_id)
    assert context["seconds_remaining"] == 60 and context["budget"]["clock_started"] is False
    session.act(run_id, ToolRequest(tool="sha256", data="a"))
    monkeypatch.setattr("metis.core.codex_session.time.time", lambda: base + 3600 + 61)
    with pytest.raises(ValueError, match="exhausted"):
        session.act(run_id, ToolRequest(tool="sha256", data="b"))
    assert session.context(run_id)["status"] == "exhausted"
    resumed = session.extend(run_id, seconds=600, actions=10)
    assert resumed["status"] == "planning" and resumed["seconds_remaining"] > 500
    assert session.act(run_id, ToolRequest(tool="sha256", data="c"))["ok"] is True
    with pytest.raises(ValueError):
        session.extend(run_id, seconds=10 * 86_400)
    session.cancel(run_id)
    with pytest.raises(ValueError):
        session.extend(run_id, seconds=60)


def test_extend_after_long_expiry_counts_from_now(tmp_path, monkeypatch):
    import time as time_module
    session = CodexSession(tmp_path / "state" / "metis.sqlite")
    note = tmp_path / "n.txt"
    note.write_text("x")
    run_id = session.intake(title="t", description="d", paths=[note], wall_seconds=7200)["run_id"]
    base = time_module.time()
    monkeypatch.setattr("metis.core.codex_session.time.time", lambda: base)
    session.act(run_id, ToolRequest(tool="sha256", data="a"))
    # 3.46 hours after the first action the 2-hour budget is long gone.
    monkeypatch.setattr("metis.core.codex_session.time.time", lambda: base + 12_456)
    with pytest.raises(ValueError, match="exhausted"):
        session.act(run_id, ToolRequest(tool="sha256", data="b"))
    resumed = session.extend(run_id, seconds=3600)
    assert resumed["status"] == "planning" and 3590 <= resumed["seconds_remaining"] <= 3600


def test_state_survives_moving_the_checkout(tmp_path):
    import shutil as shutil_module
    import sqlite3
    old = tmp_path / "old" / ".metis-state"
    session = CodexSession(old / "metis.sqlite")
    note = tmp_path / "cipher.txt"
    note.write_text("Uryyb")
    run_id = session.intake(title="t", description="d", paths=[note])["run_id"]
    with sqlite3.connect(old / "metis.sqlite") as db:
        stored = db.execute("SELECT artifact_root FROM codex_sessions").fetchone()[0]
    assert not stored.startswith("/")  # stored relative to the state directory
    shutil_module.move(str(tmp_path / "old"), str(tmp_path / "new"))
    moved = CodexSession(tmp_path / "new" / ".metis-state" / "metis.sqlite")
    assert moved.artifact(run_id, "00-cipher.txt", "text")["ok"] is True


def test_legacy_absolute_artifact_roots_are_migrated(tmp_path):
    import shutil as shutil_module
    import sqlite3
    old = tmp_path / "old" / ".metis-state"
    session = CodexSession(old / "metis.sqlite")
    note = tmp_path / "cipher.txt"
    note.write_text("Uryyb")
    run_id = session.intake(title="t", description="d", paths=[note])["run_id"]
    root = session.artifact_root(run_id)
    with sqlite3.connect(old / "metis.sqlite") as db:  # simulate a database written by an older METIS
        db.execute("UPDATE codex_sessions SET artifact_root=?", (str(root),))
    shutil_module.move(str(tmp_path / "old"), str(tmp_path / "new"))
    moved = CodexSession(tmp_path / "new" / ".metis-state" / "metis.sqlite")
    assert moved.artifact_root(run_id) == (tmp_path / "new" / ".metis-state" / root.name).resolve()
    assert moved.artifact(run_id, "00-cipher.txt", "text")["ok"] is True


def test_legacy_database_split_defaults_to_unlisted(tmp_path):
    import sqlite3

    database = tmp_path / "legacy.sqlite"
    session = CodexSession(database)
    note = tmp_path / "cipher.txt"
    note.write_text("synthetic")
    run_id = session.intake(title="t", description="d", paths=[note])["run_id"]
    with sqlite3.connect(database) as db:
        db.execute("ALTER TABLE codex_sessions DROP COLUMN evaluation_split")
    migrated = CodexSession(database)
    assert migrated.context(run_id)["evaluation_split"] == "unlisted"
