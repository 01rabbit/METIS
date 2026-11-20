from __future__ import annotations

import json
import sqlite3
import sys

import pytest

from metis.cli import main
from metis.core.ctf_web import WebWorkflow


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
    assert result["selected_runs"] == 1 and result["cookie_jars_removed"] == 1
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
    assert result["cookie_jars_removed"] == 1
    assert result["provider_revocation_required"] is True
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
