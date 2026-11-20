from __future__ import annotations

import json
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from metis.cli import main
from metis.core.ctf_web import WebWorkflow, _credential_preview_source


def _insert_credential(db: sqlite3.Connection, key: str, updated_at: float | None) -> None:
    db.execute(
        "INSERT INTO web_credentials(origin,payload,updated_at) VALUES (?,?,?)",
        (key, json.dumps({"token": f"private-{key}"}), updated_at),
    )


def test_retention_preview_is_read_only_redacted_and_classifies_cutoff(tmp_path):
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    now = 10_000_000.0
    cutoff = now - 30 * 86_400
    with sqlite3.connect(workflow.database) as db:
        _insert_credential(db, "https://old.example", cutoff - 1)
        _insert_credential(db, "https://boundary.example", cutoff)
        _insert_credential(db, "https://new.example", cutoff + 1)
        _insert_credential(db, "https://unknown.example", None)
        db.execute(
            "INSERT INTO web_runs(run_id,config,state,forms,links,salt) VALUES (?,?,?,?,?,?)",
            ("old-run", json.dumps({"auth_origin": "https://old.example"}),
             json.dumps({"cookies": {
                 "https://old.example": [{"name": "s", "value": "cookie-secret"}],
                 "https://unrelated.example": [{"name": "keep", "value": "other"}],
             }}), "[]", "[]", "synthetic"),
        )
        before = db.execute(
            "SELECT origin,payload,updated_at FROM web_credentials ORDER BY origin",
        ).fetchall()
        generations = db.execute("SELECT * FROM web_auth_generations ORDER BY origin").fetchall()

    result = workflow.credential_retention(older_than_days=30, now=now)

    assert result["applied"] is False
    assert result["eligible_credentials"] == 2
    assert result["newer_credentials_retained"] == 1
    assert result["age_unknown_retained"] == 1
    assert result["selected_runs"] == 1 and result["cookie_jars_selected"] == 1
    assert result["sqlite_wal_sidecars_may_be_created"] is True
    assert "may create/update -wal/-shm sidecars" in result["limit"]
    assert "private-" not in json.dumps(result)
    assert "old.example" not in json.dumps(result)
    with sqlite3.connect(workflow.database) as db:
        assert db.execute(
            "SELECT origin,payload,updated_at FROM web_credentials ORDER BY origin",
        ).fetchall() == before
        assert db.execute("SELECT * FROM web_auth_generations ORDER BY origin").fetchall() == generations


def test_legacy_credential_age_migrates_as_unknown_and_reauth_refreshes_timestamp(tmp_path):
    database = tmp_path / "state" / "legacy.sqlite"
    database.parent.mkdir()
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE web_credentials (origin TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("INSERT INTO web_credentials VALUES (?,?)",
                   ("https://legacy.example", '{"token":"private-legacy"}'))

    workflow = WebWorkflow(database)
    with sqlite3.connect(database) as db:
        assert db.execute(
            "SELECT updated_at FROM web_credentials WHERE origin=?",
            ("https://legacy.example",),
        ).fetchone() == (None,)

    result = workflow.credential_retention(older_than_days=1, apply=True, now=10_000_000)
    assert result["eligible_credentials"] == 0 and result["age_unknown_retained"] == 1

    # A successful reauthentication is the first reliable age marker for a legacy row.
    database.chmod(0o600)
    for suffix in ("-wal", "-shm"):
        sidecar = database.with_name(database.name + suffix)
        if sidecar.exists():
            sidecar.chmod(0o600)
    workflow.auth("https://legacy.example", kind="token", value="private-replacement")
    with sqlite3.connect(database) as db:
        updated_at, payload = db.execute(
            "SELECT updated_at,payload FROM web_credentials WHERE origin=?",
            ("https://legacy.example",),
        ).fetchone()
    assert isinstance(updated_at, float) and updated_at > 0
    assert json.loads(payload)["token"] == "private-replacement"


def test_cli_preview_does_not_create_missing_database_or_parent(tmp_path, monkeypatch, capsys):
    database = tmp_path / "missing-parent" / "state.sqlite"
    monkeypatch.setattr(sys, "argv", [
        "metis", "web", "--database", str(database),
        "credential-retention", "--older-than-days", "30",
    ])
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["applied"] is False and result["credentials_considered"] == 0
    assert not database.exists() and not database.parent.exists()


def test_cli_preview_does_not_migrate_legacy_credential_table(tmp_path, monkeypatch, capsys):
    database = tmp_path / "legacy.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE web_credentials (origin TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("INSERT INTO web_credentials VALUES (?,?)",
                   ("https://legacy.example", '{"token":"private-legacy"}'))
    before = database.stat().st_mtime_ns
    monkeypatch.setattr(sys, "argv", [
        "metis", "web", "--database", str(database),
        "credential-retention", "--older-than-days", "1",
    ])
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["age_unknown_retained"] == 1
    assert database.stat().st_mtime_ns == before
    with sqlite3.connect(database) as db:
        assert [row[1] for row in db.execute("PRAGMA table_info(web_credentials)")] == [
            "origin", "payload",
        ]


def test_cli_preview_accepts_relative_database_path(tmp_path, monkeypatch, capsys):
    database = tmp_path / "relative.sqlite"
    workflow = WebWorkflow(database)
    with sqlite3.connect(database) as db:
        _insert_credential(db, "https://old.example", 1.0)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "metis", "web", "--database", "relative.sqlite",
        "credential-retention", "--older-than-days", "1",
    ])

    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["credentials_considered"] == 1
    assert result["eligible_credentials"] == 1
    assert workflow.database == database


def test_readonly_wal_preview_creates_no_sidecars_or_needs_no_directory_write(tmp_path):
    database = tmp_path / "state" / "metis.sqlite"
    workflow = WebWorkflow(database)
    assert workflow._truncate_credential_wal() is True
    for suffix in ("-wal", "-shm"):
        sidecar = database.with_name(database.name + suffix)
        if not sidecar.exists():
            continue
        if suffix == "-wal" and sidecar.stat().st_size != 0:
            pytest.skip("test database WAL is not empty")
        sidecar.unlink()

    database.parent.chmod(0o500)
    if os.access(database.parent, os.W_OK):
        database.parent.chmod(0o700)
        pytest.skip("test process can write through the read-only directory mode")
    try:
        result = workflow.credential_retention(older_than_days=30)
        assert result["sqlite_wal_sidecars_may_be_created"] is False
        assert not database.with_name(database.name + "-wal").exists()
        assert not database.with_name(database.name + "-shm").exists()
    finally:
        database.parent.chmod(0o700)


@pytest.mark.parametrize("has_shm", [False, True])
def test_preview_reports_sidecar_requirement_for_uncheckpointed_wal(tmp_path, has_shm):
    database = tmp_path / "synthetic.sqlite"
    database.write_bytes(b"0" * 18 + b"\x02\x02")
    database.with_name(database.name + "-wal").write_bytes(b"nonempty")
    shm = database.with_name(database.name + "-shm")
    if has_shm:
        shm.write_bytes(b"existing synthetic shm")

    uri, signature, may_create_sidecars = _credential_preview_source(database)

    assert uri.endswith("?mode=ro")
    assert signature is None
    assert may_create_sidecars is True
    assert shm.exists() is has_shm


def test_concurrent_workflow_startup_serializes_credential_column_migration(tmp_path):
    database = tmp_path / "legacy-concurrent.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE web_credentials (origin TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("INSERT INTO web_credentials VALUES (?,?)",
                   ("https://legacy.example", '{"token":"private-legacy"}'))
    barrier = Barrier(3)

    def initialize() -> WebWorkflow:
        barrier.wait()
        return WebWorkflow(database)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(initialize) for _ in range(2)]
        barrier.wait()
        workflows = [future.result(timeout=10) for future in futures]

    assert len(workflows) == 2
    with sqlite3.connect(database) as db:
        assert [row[1] for row in db.execute("PRAGMA table_info(web_credentials)")] == [
            "origin", "payload", "updated_at",
        ]


def test_apply_retires_only_old_credentials_and_fences_linked_clients(tmp_path):
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    now = 10_000_000.0
    cutoff = now - 30 * 86_400
    old = "https://old.example"
    new = "https://new.example"
    unknown = "https://unknown.example"
    with sqlite3.connect(workflow.database) as db:
        _insert_credential(db, old, cutoff - 5)
        _insert_credential(db, new, cutoff + 5)
        _insert_credential(db, unknown, None)
        db.executemany(
            "INSERT INTO web_auth_generations(origin,generation) VALUES (?,?)",
            [(old, 7), (new, 3)],
        )
        for run_id, key, generation in (("old-run", old, 7), ("new-run", new, 3)):
            config = {"origins": [key], "auth_origin": key}
            state = {
                "_metis_auth_generation": generation,
                "cookies": {
                    key: [{"name": "session", "value": f"cookie-{key}"}],
                    "https://unrelated.example": [{"name": "other", "value": "keep"}],
                },
                "cookie_fingerprint": "synthetic-fingerprint",
            }
            db.execute(
                "INSERT INTO web_runs(run_id,config,state,forms,links,salt) VALUES (?,?,?,?,?,?)",
                (run_id, json.dumps(config), json.dumps(state), "[]", "[]", "synthetic"),
            )

    old_config = {"origins": [old], "auth_origin": old}
    old_state = {"_metis_auth_generation": 7, "cookies": {}}
    stale_client = workflow._client(old_config, old_state)
    result = workflow.credential_retention(older_than_days=30, apply=True, now=now)

    assert result["applied"] is True
    assert result["eligible_credentials"] == 1
    assert result["selected_runs"] == 1
    assert result["cookie_jars_selected"] == 1
    assert result["provider_revocation_required"] is True
    assert result["wal_cleanup_complete"] is True
    with pytest.raises(ValueError, match="authentication has been forgotten"):
        stale_client.request(old + "/after-retirement")
    with sqlite3.connect(workflow.database) as db:
        assert db.execute("SELECT origin FROM web_credentials ORDER BY origin").fetchall() == [
            (new,), (unknown,),
        ]
        assert db.execute(
            "SELECT generation FROM web_auth_generations WHERE origin=?", (old,),
        ).fetchone() == (8,)
        old_state_after, = db.execute(
            "SELECT state FROM web_runs WHERE run_id='old-run'",
        ).fetchone()
        new_state_after, = db.execute(
            "SELECT state FROM web_runs WHERE run_id='new-run'",
        ).fetchone()
    old_cookies = json.loads(old_state_after)["cookies"]
    assert old not in old_cookies and "https://unrelated.example" in old_cookies
    assert "cookie_fingerprint" not in json.loads(old_state_after)
    new_cookies = json.loads(new_state_after)["cookies"]
    assert new in new_cookies and "https://unrelated.example" in new_cookies


def test_retention_apply_rolls_back_generation_and_cookie_changes_on_delete_error(tmp_path):
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    key = "https://old.example"
    cutoff = 10_000_000 - 30 * 86_400
    with sqlite3.connect(workflow.database) as db:
        _insert_credential(db, key, cutoff - 1)
        db.execute("INSERT INTO web_auth_generations VALUES (?,?)", (key, 4))
        state = {"_metis_auth_generation": 4, "cookies": {key: [{"name": "s", "value": "secret"}]}}
        config = {"origins": [key], "auth_origin": key}
        db.execute(
            "INSERT INTO web_runs(run_id,config,state,forms,links,salt) VALUES (?,?,?,?,?,?)",
            ("run", json.dumps(config), json.dumps(state), "[]", "[]", "synthetic"),
        )
        db.execute("""CREATE TRIGGER reject_retention_delete BEFORE DELETE ON web_credentials
                      BEGIN SELECT RAISE(ABORT,'injected delete failure'); END""")

    with pytest.raises(sqlite3.IntegrityError, match="injected delete failure"):
        workflow.credential_retention(older_than_days=30, apply=True, now=10_000_000)

    with sqlite3.connect(workflow.database) as db:
        assert db.execute("SELECT generation FROM web_auth_generations WHERE origin=?", (key,)).fetchone() == (4,)
        assert db.execute("SELECT COUNT(*) FROM web_credentials WHERE origin=?", (key,)).fetchone() == (1,)
        state_after, = db.execute("SELECT state FROM web_runs WHERE run_id='run'").fetchone()
    assert key in json.loads(state_after)["cookies"]


@pytest.mark.parametrize("blocked_table", ["web_credentials", "web_runs"])
def test_retention_apply_rolls_back_when_trigger_suppresses_required_write(tmp_path, blocked_table):
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    key = "https://old.example"
    cutoff = 10_000_000 - 30 * 86_400
    with sqlite3.connect(workflow.database) as db:
        _insert_credential(db, key, cutoff - 1)
        db.execute("INSERT INTO web_auth_generations VALUES (?,?)", (key, 4))
        state = {"_metis_auth_generation": 4, "cookies": {key: [{"name": "s", "value": "secret"}]}}
        config = {"origins": [key], "auth_origin": key}
        db.execute(
            "INSERT INTO web_runs(run_id,config,state,forms,links,salt) VALUES (?,?,?,?,?,?)",
            ("run", json.dumps(config), json.dumps(state), "[]", "[]", "synthetic"),
        )
        table = "web_credentials" if blocked_table == "web_credentials" else "web_runs"
        operation = "DELETE" if blocked_table == "web_credentials" else "UPDATE"
        db.execute(
            f"CREATE TRIGGER suppress_retirement BEFORE {operation} ON {table} "
            "BEGIN SELECT RAISE(IGNORE); END",
        )

    with pytest.raises(sqlite3.IntegrityError, match="retire|retired"):
        workflow.credential_retention(older_than_days=30, apply=True, now=10_000_000)

    with sqlite3.connect(workflow.database) as db:
        assert db.execute("SELECT generation FROM web_auth_generations WHERE origin=?", (key,)).fetchone() == (4,)
        assert db.execute("SELECT COUNT(*) FROM web_credentials WHERE origin=?", (key,)).fetchone() == (1,)
        state_after, = db.execute("SELECT state FROM web_runs WHERE run_id='run'").fetchone()
    assert key in json.loads(state_after)["cookies"]


def test_retention_retries_wal_cleanup_after_busy_reader_is_released(tmp_path):
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    key = "https://old.example"
    with sqlite3.connect(workflow.database) as db:
        _insert_credential(db, key, 1.0)
    reader = sqlite3.connect(workflow.database)
    keeper = sqlite3.connect(workflow.database)
    reader.execute("BEGIN")
    assert reader.execute("SELECT payload FROM web_credentials WHERE origin=?", (key,)).fetchone()
    try:
        first = workflow.credential_retention(older_than_days=1, apply=True, now=10_000_000)
        assert first["eligible_credentials"] == 1
        assert first["wal_cleanup_complete"] is False
        wal_path = workflow.database.with_name(workflow.database.name + "-wal")
        assert b"private-https://old.example" in wal_path.read_bytes()
    finally:
        reader.close()

    retry = workflow.credential_retention(older_than_days=1, apply=True, now=10_000_000)
    assert retry["eligible_credentials"] == 0
    assert retry["wal_cleanup_complete"] is True
    wal_path = workflow.database.with_name(workflow.database.name + "-wal")
    assert not wal_path.exists() or wal_path.stat().st_size == 0
    assert b"private-https://old.example" not in workflow.database.read_bytes()
    keeper.close()


def test_credential_retention_cli_previews_by_default_and_requires_apply_to_delete(tmp_path, monkeypatch, capsys):
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    with sqlite3.connect(workflow.database) as db:
        _insert_credential(db, "https://old.example", 1.0)
    monkeypatch.setattr(sys, "argv", [
        "metis", "web", "--database", str(workflow.database),
        "credential-retention", "--older-than-days", "30",
    ])
    assert main() == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["applied"] is False and preview["eligible_credentials"] == 1
    with sqlite3.connect(workflow.database) as db:
        assert db.execute("SELECT COUNT(*) FROM web_credentials").fetchone() == (1,)

    monkeypatch.setattr(sys, "argv", [
        "metis", "web", "--database", str(workflow.database),
        "credential-retention", "--older-than-days", "30", "--apply",
    ])
    assert main() == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied["applied"] is True and applied["eligible_credentials"] == 1
    assert applied["wal_cleanup_complete"] is True
    with sqlite3.connect(workflow.database) as db:
        assert db.execute("SELECT COUNT(*) FROM web_credentials").fetchone() == (0,)


def test_retention_refuses_more_than_one_hundred_origins_without_changes(tmp_path):
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    with sqlite3.connect(workflow.database) as db:
        db.executemany(
            "INSERT INTO web_credentials(origin,payload,updated_at) VALUES (?,?,?)",
            [(f"https://site{i}.example", "{}", 1.0) for i in range(101)],
        )
    with pytest.raises(ValueError, match="exceeds 100 origins"):
        workflow.credential_retention(older_than_days=30, apply=True, now=10_000_000)
    with sqlite3.connect(workflow.database) as db:
        assert db.execute("SELECT COUNT(*) FROM web_credentials").fetchone() == (101,)


def test_retention_refuses_more_than_one_thousand_linked_runs_atomically(tmp_path):
    workflow = WebWorkflow(tmp_path / "state" / "metis.sqlite")
    key = "https://old.example"
    with sqlite3.connect(workflow.database) as db:
        _insert_credential(db, key, 1.0)
        db.executemany(
            "INSERT INTO web_runs(run_id,config,state,forms,links,salt) VALUES (?,?,?,?,?,?)",
            [(f"run-{i}", json.dumps({"auth_origin": key}),
              json.dumps({"cookies": {key: [{"name": "s", "value": "secret"}]}}),
              "[]", "[]", "synthetic") for i in range(1001)],
        )
    with pytest.raises(ValueError, match="exceeds 1000 linked runs"):
        workflow.credential_retention(older_than_days=1, apply=True, now=10_000_000)
    with sqlite3.connect(workflow.database) as db:
        assert db.execute("SELECT COUNT(*) FROM web_credentials").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM web_auth_generations WHERE origin=?",
                          (key,)).fetchone() == (0,)
