"""Scoped URL intake and official CTFd, rCTF, ksnctf and configured-form verdicts."""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import math
import os
import re
import secrets
import sqlite3
import stat
import tempfile
import time
import urllib.error
import urllib.parse
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from metis.core import ctf_browser, ctf_rctf
from metis.core.answer_vault import split_for
from metis.core.codex_session import CodexSession
from metis.core.contracts import RunStatus
from metis.core.ctf_html import Page, display_url
from metis.core.ctf_http import SafeHTTP, clean_url, origin
from metis.core.ctf_knowledge import KnowledgeBase
from metis.core.ctf_ksnctf import KsnctfVerdict, is_official_problem, problem_id
from metis.core.resources import ResourceBroker
from metis.core.run_lock import locked

NETWORK_ERRORS = (OSError, ValueError, KeyError, TypeError, RuntimeError, http.client.HTTPException)
# Live application pages are never treated as distribution files.
PAGE_SUFFIXES = {".php", ".html", ".htm", ".cgi", ".asp", ".aspx", ".jsp"}
ATTACHMENTS = {".apk", ".dex", ".jar", ".so", ".dll", ".out", ".pyc", ".wasm", ".img", ".iso", ".dmp",
               ".mem", ".raw", ".vmdk", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt", ".bmp",
               ".gif", ".mp3", ".mp4", ".flac", ".svg", ".js", ".json", ".csv", ".sqlite", ".db",
               ".enc", ".key", ".pem", ".pub", ".cap", ".py", ".rb", ".go", ".rs", ".java", ".s", ".asm",
               ".zip", ".tar", ".gz", ".xz", ".bz2", ".7z", ".rar", ".bin", ".elf", ".exe",
               ".png", ".jpg", ".jpeg", ".wav", ".pcap", ".pcapng", ".pdf", ".txt", ".c", ".cpp", ".class"}


class WebRequest(BaseModel):
    """One scoped HTTP request against a granted challenge origin."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    url: str = Field(min_length=1, max_length=8192)
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict, max_length=32)
    data: str | None = Field(default=None, max_length=131_072)
    data_hex: str | None = Field(default=None, max_length=262_144)
    form: dict[str, str] | None = Field(default=None, max_length=128)
    json_body: Any = Field(default=None, alias="json")
    follow: bool = False
    extract: str | None = Field(default=None, max_length=512)
    preview: int = Field(default=4096, ge=0, le=65_536)
    save: bool = False

    def body(self) -> tuple[bytes | None, dict[str, str]]:
        given = [self.data is not None, self.data_hex is not None, self.form is not None,
                 self.json_body is not None]
        if sum(given) > 1:
            raise ValueError("use one of data, data_hex, form or json")
        headers = dict(self.headers)
        lowered = {key.lower() for key in headers}
        if self.form is not None:
            if "content-type" not in lowered:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            return urllib.parse.urlencode(self.form).encode(), headers
        if self.json_body is not None:
            if "content-type" not in lowered:
                headers["Content-Type"] = "application/json"
            return json.dumps(self.json_body).encode(), headers
        if self.data_hex is not None:
            return bytes.fromhex(self.data_hex), headers
        if self.data is not None:
            return self.data.encode(), headers
        return None, headers


TRANSIENT_DOWNLOAD_ERRORS = (http.client.IncompleteRead, http.client.RemoteDisconnected,
                             ConnectionResetError, TimeoutError, urllib.error.URLError)
# Distribution files that a platform serves from its own storage on another origin.
PLATFORM_FILE_ORIGINS = {
    "https://alpacahack.com": ["https://alpacahack-prod.s3.ap-northeast-1.amazonaws.com"],
}
# Platforms whose flags are submitted in the user's logged-in browser, not by METIS.
BROWSER_SUBMISSION_ORIGINS = {"https://alpacahack.com"}


def is_distribution(link: dict, page_url: str, adapter: str, challenge_id: int | str | None) -> bool:
    """Decide whether a problem-page link is a distribution file to snapshot."""
    if link.get("download"):
        return True
    path = urllib.parse.urlsplit(link["url"]).path
    name = Path(path).name.lower()
    suffix = Path(name).suffix
    if suffix in PAGE_SUFFIXES:
        return False
    # ksnctf serves each problem's files under /q/<id>/ (including extensionless
    # binaries and versioned libraries such as libc.so.6).
    if adapter == "ksnctf" and challenge_id is not None:
        try:
            same_origin = origin(link["url"]) == origin(page_url)
        except ValueError:
            same_origin = False
        if same_origin and path.startswith(f"/q/{challenge_id}/") and name:
            return True
    return bool(suffix in ATTACHMENTS or re.fullmatch(r".+\.so(\.[0-9]+)+", name))


def feedback_text(value: str, candidate: str, client: SafeHTTP) -> str:
    for secret in [candidate, *client.secret_values()]:
        if secret:
            value = value.replace(secret, "[redacted]")
    value = re.sub(r"(?:FLAG|flag)_[^\s<>\"']{1,200}|[A-Za-z0-9_]{1,32}\{[^{}\r\n]{1,200}\}",
                   "[candidate redacted]", value)
    return value[:512]


class WebWorkflow:
    _AUTH_GENERATION_STATE_KEY = "_metis_auth_generation"
    _COOKIE_EPOCH_STATE_KEY = "_metis_cookie_epoch"

    @staticmethod
    def _environment_auth_only() -> bool:
        mode = os.environ.get("METIS_WEB_AUTH_STORAGE", "local")
        if mode not in {"local", "environment"}:
            raise ValueError("METIS_WEB_AUTH_STORAGE must be local or environment")
        return mode == "environment"

    def __init__(self, database: Path):
        self.database = database
        self._check_auth_storage(private=False, allow_missing=True)
        self.session = CodexSession(database)
        self.knowledge = KnowledgeBase(database)
        with sqlite3.connect(database) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS web_runs (
                run_id TEXT PRIMARY KEY, config TEXT NOT NULL, state TEXT NOT NULL,
                forms TEXT NOT NULL, links TEXT NOT NULL, salt TEXT NOT NULL,
                paused_until REAL NOT NULL DEFAULT 0)""")
            db.execute("""CREATE TABLE IF NOT EXISTS web_attempts (
                run_id TEXT NOT NULL, digest TEXT NOT NULL, verdict TEXT NOT NULL,
                created REAL NOT NULL, PRIMARY KEY(run_id, digest))""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(web_attempts)")}
            if "attempts" not in columns:
                db.execute("ALTER TABLE web_attempts ADD COLUMN attempts INTEGER NOT NULL DEFAULT 1")
            db.execute("CREATE TABLE IF NOT EXISTS web_credentials (origin TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            credential_columns = {row[1] for row in db.execute("PRAGMA table_info(web_credentials)")}
            if "updated_at" not in credential_columns:
                # Legacy credentials have unknown age and are never auto-retired.
                db.execute("ALTER TABLE web_credentials ADD COLUMN updated_at REAL")
            db.execute("CREATE TABLE IF NOT EXISTS web_auth_generations (origin TEXT PRIMARY KEY, generation INTEGER NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS web_cookie_retirement (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                epoch INTEGER NOT NULL CHECK (typeof(epoch) = 'integer' AND epoch > 0))""")

    def _check_auth_storage(self, *, private: bool, allow_missing: bool = False) -> bool:
        owner_private = True
        for suffix, label in (("", "database"), ("-wal", "WAL"), ("-shm", "SHM")):
            try:
                info = self.database.with_name(self.database.name + suffix).lstat()
            except FileNotFoundError:
                if suffix or allow_missing:
                    continue
                raise ValueError("web authentication state database is missing") from None
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f"web authentication state {label} must be a regular file")
            if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                if private:
                    raise ValueError(f"web authentication state {label} must be private and owned by the current user")
                owner_private = False
        return owner_private

    def _check_web_storage(self) -> bool:
        return self._check_auth_storage(private=not self._environment_auth_only())

    @staticmethod
    def _discard_auth_cookies(state: dict, auth_origin: str, private_storage: bool) -> None:
        if private_storage:
            state.get("cookies", {}).pop(auth_origin, None)
        else:
            state.pop("cookies", None)
        state.pop("cookie_fingerprint", None)

    @staticmethod
    def _cookie_epoch(db: sqlite3.Connection) -> int:
        row = db.execute("SELECT epoch FROM web_cookie_retirement WHERE singleton=1").fetchone()
        return int(row[0]) if row is not None else 0

    def _client_state_for_storage(self, client: SafeHTTP, auth_origin: str, generation: int,
                                  *, private_storage: bool, cookie_epoch: int) -> dict:
        state = client.export_state()
        keep_run_cookies = private_storage and getattr(client, "_metis_cookie_epoch", 0) == cookie_epoch
        if (not keep_run_cookies or self._environment_auth_only()
                or getattr(client, "_metis_environment_only", False) or generation != client.auth_generation):
            self._discard_auth_cookies(state, auth_origin, keep_run_cookies)
        state[self._AUTH_GENERATION_STATE_KEY] = generation
        return state

    def auth(self, url: str, *, kind: str, value: str, scheme: str = "Token") -> dict:
        if self._environment_auth_only():
            raise ValueError("stored web authentication is disabled; use --token-env or --cookie-env")
        self._check_auth_storage(private=True)
        key = origin(url)
        if kind not in {"token", "cookie"} or not value or len(value) > 16384 or any(char in value for char in "\r\n"):
            raise ValueError("invalid private CTF credential")
        if scheme not in {"Token", "Bearer"}:
            raise ValueError("invalid credential scheme")
        with sqlite3.connect(self.database) as db:
            # Best effort for deleted/updated cells in the main database. This
            # does not erase WAL frames, snapshots, backups, or provider state.
            db.execute("PRAGMA secure_delete=ON")
            db.execute("BEGIN IMMEDIATE")
            # One origin has one active stored credential. A replacement also
            # invalidates cookies derived from the previous authentication.
            values = {kind: value, "scheme": scheme}
            db.execute("INSERT INTO web_credentials(origin,payload,updated_at) VALUES (?,?,?) "
                       "ON CONFLICT(origin) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                       (key, json.dumps(values), time.time()))
            db.execute("INSERT INTO web_auth_generations(origin,generation) VALUES (?,1) "
                       "ON CONFLICT(origin) DO UPDATE SET generation=generation+1", (key,))
            generation, = db.execute("SELECT generation FROM web_auth_generations WHERE origin=?",
                                     (key,)).fetchone()
            rows = db.execute("SELECT run_id,state FROM web_runs WHERE json_extract(config,'$.auth_origin')=?",
                              (key,)).fetchall()
            for run_id, raw_state in rows:
                state = json.loads(raw_state)
                state.get("cookies", {}).pop(key, None)
                state.pop("cookie_fingerprint", None)
                state[self._AUTH_GENERATION_STATE_KEY] = generation
                db.execute("UPDATE web_runs SET state=? WHERE run_id=?", (json.dumps(state), run_id))
        return {"origin": key, "credential_stored": True, "kind": kind,
                "storage": "private local state; excluded from Git"}

    def forget_auth(self, url: str) -> dict:
        """Forget locally stored credentials and cookies for one authentication origin."""
        key = origin(url)
        self._check_auth_storage(private=False)
        with sqlite3.connect(self.database) as db:
            db.execute("PRAGMA secure_delete=ON")
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO web_auth_generations(origin,generation) VALUES (?,1) "
                       "ON CONFLICT(origin) DO UPDATE SET generation=generation+1", (key,))
            generation, = db.execute("SELECT generation FROM web_auth_generations WHERE origin=?",
                                     (key,)).fetchone()
            cursor = db.execute("DELETE FROM web_credentials WHERE origin=?", (key,))
            rows = db.execute("SELECT run_id,state FROM web_runs WHERE json_extract(config,'$.auth_origin')=?", (key,)).fetchall()
            cookie_removed = False
            for run_id, raw_state in rows:
                state = json.loads(raw_state)
                removed_cookies = state.get("cookies", {}).pop(key, None)
                cookie_removed = bool(removed_cookies) or cookie_removed
                state.pop("cookie_fingerprint", None)
                state[self._AUTH_GENERATION_STATE_KEY] = generation
                db.execute("UPDATE web_runs SET state=? WHERE run_id=?", (json.dumps(state), run_id))
            removed = cursor.rowcount > 0 or cookie_removed
        return {"origin": key, "credential_removed": removed,
                "provider_revocation_required": True,
                "limit": ("Local stored credentials only; environment variables and provider credentials "
                          "are unchanged, an in-flight request may already have sent authentication, "
                          "and SQLite WAL, snapshots and backups may retain prior values")}

    def forget_all_auth(self, *, apply: bool = False, include_run_cookies: bool = False) -> dict:
        """Preview or retire saved platform authentication and optionally all cookie jars."""
        self._check_auth_storage(private=False)
        with sqlite3.connect(self.database) as db:
            if apply:
                db.execute("PRAGMA secure_delete=ON")
            db.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
            credentials = db.execute("SELECT origin FROM web_credentials LIMIT 101").fetchall()
            runs = db.execute("SELECT run_id,config,state FROM web_runs LIMIT 1001").fetchall()
            if len(credentials) > 100 or len(runs) > 1000:
                raise ValueError("bulk auth forgetting exceeds 100 origins or 1000 runs; use web forget URL per origin")
            origins = {row[0] for row in credentials}
            selected: list[tuple[str, str, dict]] = []
            for run_id, raw_config, raw_state in runs:
                config, state = json.loads(raw_config), json.loads(raw_state)
                key = config.get("auth_origin") if isinstance(config, dict) else None
                if (not isinstance(key, str) or not isinstance(state, dict)
                        or not isinstance(state.get("cookies", {}), dict)):
                    raise TypeError("stored web authentication state is invalid")
                origins.add(key)
                selected.append((run_id, key, state))
            if len(origins) > 100:
                raise ValueError("bulk auth forgetting exceeds 100 origins")
            cookie_jars = sum(len(state.get("cookies", {})) for _, _, state in selected) if include_run_cookies else 0
            if apply:
                generations: dict[str, int] = {}
                for key in sorted(origins):
                    db.execute("INSERT INTO web_auth_generations(origin,generation) VALUES (?,1) "
                               "ON CONFLICT(origin) DO UPDATE SET generation=generation+1", (key,))
                    generations[key] = db.execute("SELECT generation FROM web_auth_generations WHERE origin=?",
                                                  (key,)).fetchone()[0]
                db.execute("DELETE FROM web_credentials")
                if include_run_cookies:
                    db.execute("INSERT INTO web_cookie_retirement (singleton,epoch) VALUES (1,1) "
                               "ON CONFLICT(singleton) DO UPDATE SET epoch=epoch+1")
                for run_id, key, state in selected:
                    self._discard_auth_cookies(state, key, not include_run_cookies)
                    state[self._AUTH_GENERATION_STATE_KEY] = generations[key]
                    db.execute("UPDATE web_runs SET state=? WHERE run_id=?", (json.dumps(state), run_id))
        result = {"applied": apply, "origins": len(origins), "stored_credentials": len(credentials),
                  "selected_runs": len(runs), "provider_revocation_required": apply,
                  "limit": ("Local platform-authentication state only; environment variables, "
                            "challenge-origin cookies, provider credentials, in-flight requests or intake, "
                            "SQLite WAL, snapshots and backups may retain prior values")}
        if include_run_cookies:
            result.update(run_cookie_jars=cookie_jars, limit=(
                "Local authentication and all saved run cookies only. Environment variables, provider credentials, "
                "in-flight requests, SQLite WAL, snapshots and backups may retain prior values."
            ))
        return result

    @classmethod
    def preview_credential_retention(cls, database: Path, *, older_than_days: int,
                                     now: float | None = None) -> dict:
        """Run a credential-age preview without constructing or migrating workflow state."""
        preview = cls.__new__(cls)
        preview.database = database
        return preview.credential_retention(older_than_days=older_than_days, now=now)

    def credential_retention(self, *, older_than_days: int, apply: bool = False,
                             now: float | None = None) -> dict:
        """Preview or retire locally stored credentials with a known old timestamp."""
        if type(older_than_days) is not int or not 1 <= older_than_days <= 36_500:
            raise ValueError("credential retention age must be 1 to 36500 days")
        current = time.time() if now is None else now
        if isinstance(current, bool) or not isinstance(current, (int, float)) or not math.isfinite(current):
            raise ValueError("credential retention clock must be a finite timestamp")
        cutoff = float(current) - older_than_days * 86_400
        self._check_auth_storage(private=False, allow_missing=not apply)
        rows: list[tuple[str, float | None]] = []
        old_origins: list[str] = []
        newer = unknown = selected_runs = removed_cookie_jars = 0
        if apply or self.database.exists():
            connection = (sqlite3.connect(self.database) if apply else
                          sqlite3.connect(self.database.absolute().as_uri() + "?mode=ro", uri=True))
            with connection as db:
                if apply:
                    db.execute("PRAGMA secure_delete=ON")
                    db.execute("BEGIN IMMEDIATE")
                else:
                    db.execute("PRAGMA query_only=ON")
                    db.execute("BEGIN")
                tables = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'",
                )}
                credential_columns = ({row[1] for row in db.execute("PRAGMA table_info(web_credentials)")}
                                      if "web_credentials" in tables else set())
                if "web_credentials" in tables:
                    if "updated_at" in credential_columns:
                        rows = db.execute(
                            "SELECT origin,updated_at FROM web_credentials ORDER BY origin LIMIT 101",
                        ).fetchall()
                    else:
                        rows = db.execute(
                            "SELECT origin,NULL FROM web_credentials ORDER BY origin LIMIT 101",
                        ).fetchall()
                if len(rows) > 100:
                    raise ValueError("credential retention exceeds 100 origins")
                for key, updated_at in rows:
                    if (updated_at is None or isinstance(updated_at, bool)
                            or not isinstance(updated_at, (int, float))):
                        unknown += 1
                    else:
                        timestamp = float(updated_at)
                        if not math.isfinite(timestamp):
                            unknown += 1
                        elif timestamp <= cutoff:
                            old_origins.append(key)
                        else:
                            newer += 1

                if old_origins and "web_runs" in tables:
                    if apply:
                        for key in old_origins:
                            db.execute("INSERT INTO web_auth_generations(origin,generation) VALUES (?,1) "
                                       "ON CONFLICT(origin) DO UPDATE SET generation=generation+1", (key,))
                    placeholders = ",".join("?" for _ in old_origins)
                    runs = db.execute(
                        "SELECT run_id,config,state FROM web_runs "
                        f"WHERE json_extract(config,'$.auth_origin') IN ({placeholders}) LIMIT 1001",
                        old_origins,
                    ).fetchall()
                    if len(runs) > 1000:
                        raise ValueError("credential retention exceeds 1000 linked runs")
                    selected_runs = len(runs)
                    generations = ({
                        key: db.execute("SELECT generation FROM web_auth_generations WHERE origin=?",
                                        (key,)).fetchone()[0]
                        for key in old_origins
                    } if apply else {})
                    for run_id, raw_config, raw_state in runs:
                        config, state = json.loads(raw_config), json.loads(raw_state)
                        auth_origin = config.get("auth_origin") if isinstance(config, dict) else None
                        if (auth_origin not in old_origins or not isinstance(state, dict)
                                or not isinstance(state.get("cookies", {}), dict)):
                            raise TypeError("stored web authentication state is invalid")
                        cookies = state.get("cookies", {})
                        removed_cookie_jars += int(auth_origin in cookies)
                        if apply:
                            cookies.pop(auth_origin, None)
                            state.pop("cookie_fingerprint", None)
                            state[self._AUTH_GENERATION_STATE_KEY] = generations[auth_origin]
                            db.execute("UPDATE web_runs SET state=? WHERE run_id=?",
                                       (json.dumps(state), run_id))
                    if apply:
                        db.executemany("DELETE FROM web_credentials WHERE origin=?",
                                       [(key,) for key in old_origins])

        return {
            "applied": apply,
            "older_than_days": older_than_days,
            "retire_before": cutoff,
            "credentials_considered": len(rows),
            "eligible_credentials": len(old_origins),
            "newer_credentials_retained": newer,
            "age_unknown_retained": unknown,
            "selected_runs": selected_runs,
            "cookie_jars_selected": removed_cookie_jars,
            "provider_revocation_required": bool(apply and old_origins),
            "limit": ("Only locally stored credentials with a known timestamp are eligible. "
                      "Environment variables, provider state, in-flight requests, SQLite WAL, "
                      "snapshots and backups may retain prior values."),
        }

    def _load(self, run_id: str) -> tuple[dict, dict, list, list, str, float]:
        private_storage = self._check_web_storage()
        with sqlite3.connect(self.database) as db:
            db.execute("BEGIN")
            row = db.execute("SELECT config,state,forms,links,salt,paused_until FROM web_runs WHERE run_id=?",
                             (run_id,)).fetchone()
            if row is None:
                raise ValueError("web workflow not found")
            config, state = json.loads(row[0]), json.loads(row[1])
            auth_origin = config["auth_origin"]
            generation_row = db.execute("SELECT generation FROM web_auth_generations WHERE origin=?",
                                        (auth_origin,)).fetchone()
            generation = generation_row[0] if generation_row else 0
            state_generation = state.get(self._AUTH_GENERATION_STATE_KEY, generation)
            if not private_storage or self._environment_auth_only() or state_generation != generation:
                self._discard_auth_cookies(state, auth_origin, private_storage)
            state[self._AUTH_GENERATION_STATE_KEY] = generation
            state[self._COOKIE_EPOCH_STATE_KEY] = self._cookie_epoch(db)
        return config, state, json.loads(row[2]), json.loads(row[3]), row[4], row[5]

    def _client(self, config: dict, state: dict) -> SafeHTTP:
        environment_only = self._environment_auth_only()
        private_storage = self._check_auth_storage(private=not environment_only)
        with sqlite3.connect(self.database) as db:
            db.execute("BEGIN")
            row = None if environment_only else db.execute(
                "SELECT payload FROM web_credentials WHERE origin=?", (config["auth_origin"],)).fetchone()
            row_generation = db.execute("SELECT generation FROM web_auth_generations WHERE origin=?",
                                        (config["auth_origin"],)).fetchone()
            current_generation = row_generation[0] if row_generation else 0
            cookie_epoch = self._cookie_epoch(db)
        state_generation = state.get(self._AUTH_GENERATION_STATE_KEY, current_generation)
        keep_run_cookies = private_storage and state.get(self._COOKIE_EPOCH_STATE_KEY, cookie_epoch) == cookie_epoch
        if environment_only or not keep_run_cookies:
            self._discard_auth_cookies(state, config["auth_origin"], keep_run_cookies)
        client = SafeHTTP(config["origins"], auth_origin=config["auth_origin"],
                        token_env=config.get("token_env"), cookie_env=config.get("cookie_env"),
                        state=state, credentials=json.loads(row[0]) if row else
                        {"scheme": "Bearer"} if config.get("adapter") == "rctf" else {}, timeout=15)
        client.auth_generation = state_generation
        client._metis_environment_only = environment_only
        client._metis_cookie_epoch = cookie_epoch
        client.auth_generation_check = lambda expected: (
            self._environment_auth_only() == environment_only
            and self._auth_generation_matches(config["auth_origin"], expected))
        return client

    def _auth_generation_matches(self, auth_origin: str, expected: int) -> bool:
        self._check_web_storage()
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT generation FROM web_auth_generations WHERE origin=?",
                             (auth_origin,)).fetchone()
        return (row[0] if row else 0) == expected

    def _save_client(self, run_id: str, client: SafeHTTP) -> None:
        private_storage = self._check_web_storage()
        with sqlite3.connect(self.database) as db:
            db.execute("BEGIN IMMEDIATE")
            cookie_epoch = self._cookie_epoch(db)
            if getattr(client, "_metis_cookie_epoch", 0) != cookie_epoch:
                return
            config_row = db.execute("SELECT config FROM web_runs WHERE run_id=?", (run_id,)).fetchone()
            if config_row is None:
                return
            auth_origin = json.loads(config_row[0])["auth_origin"]
            row = db.execute("SELECT generation FROM web_auth_generations WHERE origin=?", (auth_origin,)).fetchone()
            generation = row[0] if row else 0
            state = self._client_state_for_storage(
                client, auth_origin, generation, private_storage=private_storage, cookie_epoch=cookie_epoch,
            )
            db.execute("UPDATE web_runs SET state=? WHERE run_id=?",
                       (json.dumps(state), run_id))

    def rctf_login(self, url: str, team_token: str) -> dict:
        """Exchange an rCTF team token for an auth token and store it privately as Bearer."""
        if self._environment_auth_only():
            raise ValueError("stored web authentication is disabled; use --token-env")
        self._check_auth_storage(private=True)
        if not team_token or len(team_token) > 4096 or any(char in team_token for char in "\r\n"):
            raise ValueError("invalid rCTF team token")
        key = origin(url)
        client = SafeHTTP([key], auth_origin=key, timeout=15)
        response = client.request(key + "/api/v1/auth/login", method="POST",
                                  body=json.dumps({"teamToken": team_token}).encode(),
                                  headers={"Content-Type": "application/json"}, sensitive=True,
                                  max_bytes=65_536, follow_redirects=False)
        payload = json.loads(response.body) if response.body else {}
        data = payload.get("data") if isinstance(payload, dict) else None
        token = data.get("authToken") if isinstance(data, dict) else None
        if response.status != 200 or payload.get("kind") != "goodLogin" or not isinstance(token, str):
            raise ValueError("rCTF login was not accepted")
        return self.auth(url, kind="token", value=token, scheme="Bearer")

    def catalog(self, url: str, *, token_env: str | None = None,
                cookie_env: str | None = None, adapter: str = "ctfd") -> dict[str, Any]:
        """Return a bounded CTFd or rCTF challenge catalog suitable for contest intake."""
        url = clean_url(url)
        base = url.rstrip("/")
        config = {"origins": [origin(url)], "auth_origin": origin(url),
                  "token_env": token_env, "cookie_env": cookie_env, "adapter": adapter}
        client = self._client(config, {})
        if adapter == "rctf":
            response = client.request(origin(url) + "/api/v1/challs", max_bytes=8 * 1024 * 1024)
            if response.status != 200:
                raise ValueError("rCTF catalog retrieval failed; check URL and Bearer authentication")
            listing = []
            for item in ctf_rctf.challenges(json.loads(response.body)):
                points, solves = item.get("points", 1), item.get("solves", 0)
                if not isinstance(points, (int, float)) or not isinstance(solves, int) or solves < 0:
                    raise ValueError("invalid rCTF score metadata")
                category = str(item.get("category", "misc"))[:40].lower() or "misc"
                listing.append({"challenge_id": ctf_rctf.challenge_key(item.get("id")),
                                "title": str(item.get("name", "challenge"))[:200], "category": category,
                                "points": float(points), "solves": solves,
                                "estimated_minutes": 30, "confidence": 0.35,
                                "url": origin(url), "adapter": "rctf"})
            return {"source": "rctf", "base_url": display_url(url), "challenges": listing,
                    "count": len(listing), "credentials_exposed": False}
        if adapter != "ctfd":
            raise ValueError("catalog adapter must be ctfd or rctf")
        response = client.request(base + "/api/v1/challenges", max_bytes=8 * 1024 * 1024)
        if response.status != 200:
            raise ValueError("CTFd catalog retrieval failed; check URL and authentication")
        payload = json.loads(response.body)
        items = payload.get("data") if payload.get("success") is True else None
        if not isinstance(items, list) or len(items) > 500:
            raise ValueError("unrecognized or oversized CTFd catalog")
        challenges = []
        for item in items:
            if not isinstance(item, dict):
                raise TypeError("invalid CTFd catalog item")
            identity = item.get("id")
            title = item.get("name")
            if not isinstance(identity, int) or not 1 <= identity <= 1_000_000 \
                    or not isinstance(title, str) or not title:
                raise ValueError("invalid CTFd challenge identity")
            solves = item.get("solves", 0)
            value = item.get("value", 1)
            if not isinstance(solves, int) or solves < 0 or not isinstance(value, (int, float)):
                raise ValueError("invalid CTFd score metadata")
            category = str(item.get("category", "misc"))[:40].lower() or "misc"
            challenges.append({"challenge_id": str(identity), "title": title[:200],
                               "category": category, "points": float(value), "solves": solves,
                               "estimated_minutes": 30, "confidence": 0.35,
                               "url": base, "adapter": "ctfd"})
        return {"source": "ctfd", "base_url": display_url(url), "challenges": challenges,
                "count": len(challenges), "credentials_exposed": False}

    def open(self, url: str, *, adapter: str = "auto", challenge_id: int | str | None = None,
             allowed_origins: list[str] | None = None, token_env: str | None = None,
             cookie_env: str | None = None, download: bool = True, render: bool = False,
             renderer: ctf_browser.Renderer | None = None) -> dict:
        url = clean_url(url)
        if adapter == "auto":
            adapter = "ksnctf" if is_official_problem(url) else "html"
        if adapter not in {"html", "ctfd", "ksnctf", "rctf"}:
            raise ValueError("adapter must be auto, html, ctfd, rctf or ksnctf")
        if render and adapter != "html":
            raise ValueError("JavaScript rendering applies to the html adapter")
        if adapter in {"ctfd", "ksnctf"} and isinstance(challenge_id, str):
            if not challenge_id.isdigit():
                raise ValueError("numeric challenge ID required")
            challenge_id = int(challenge_id)
        if adapter == "rctf":
            if challenge_id is None:
                raise ValueError("rCTF challenge ID is required")
            challenge_id = ctf_rctf.challenge_key(challenge_id)
        if adapter == "ksnctf":
            inferred_id = problem_id(url)
            if challenge_id is not None and challenge_id != inferred_id:
                raise ValueError("ksnctf challenge ID does not match the problem URL")
            challenge_id = inferred_id
        extra = list(allowed_origins or [])
        if origin(url) in PLATFORM_FILE_ORIGINS:
            # Platform-operated distribution storage (e.g. AlpacaHack's S3 bucket).
            extra.extend(PLATFORM_FILE_ORIGINS[origin(url)])
        allowed = list(dict.fromkeys([origin(url), *[origin(item) for item in extra]]))
        if len(allowed) > 16:
            raise ValueError("too many allowed origins")
        config: dict[str, Any] = {"page_url": url, "adapter": adapter, "origins": allowed,
                  "auth_origin": origin(url), "token_env": token_env, "cookie_env": cookie_env,
                  "challenge_id": challenge_id, "max_submissions": 10}
        client = self._client(config, {})
        request_url = url
        if adapter == "ctfd":
            if not isinstance(challenge_id, int) or not 1 <= challenge_id <= 1_000_000:
                raise ValueError("CTFd challenge ID is required")
            config["base_url"] = url.rstrip("/")
            request_url = config["base_url"] + "/api/v1/challenges/" + str(challenge_id)
        if adapter == "rctf":
            config["base_url"] = origin(url)
            request_url = config["base_url"] + "/api/v1/challs"
        for attempt in range(3):
            try:
                response = client.request(request_url,
                                          max_bytes=8 * 1024 * 1024 if adapter == "rctf" else 2_097_152)
                break
            except (http.client.RemoteDisconnected, ConnectionResetError, TimeoutError):
                # Idempotent GET of the statement: retry transient server/proxy drops.
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
                client.requests = 0
        if response.status != 200:
            raise ValueError("problem retrieval failed; check URL and CTF authentication")
        if adapter == "ksnctf" and (
            origin(response.url) != origin(url) or problem_id(response.url) != challenge_id
        ):
            raise ValueError("ksnctf problem retrieval redirected to another problem or origin")
        body = response.body.decode("utf-8", errors="replace")
        files = []
        rendered: dict[str, Any] | None = None
        if render:
            auth_generation_check = lambda: self._auth_generation_matches(
                config["auth_origin"], client.auth_generation)
            if not auth_generation_check():
                raise ValueError("authentication has been forgotten for this origin")
            jar_cookies = client.export_state()["cookies"].get(config["auth_origin"], [])
            host = urllib.parse.urlsplit(config["auth_origin"]).hostname or ""
            browser_cookies = [{"name": item["name"], "value": item["value"] or "", "domain": host,
                                "path": item["path"] or "/", "secure": bool(item["secure"])}
                               for item in jar_cookies]
            # A configured `browser` capacity is shared by every METIS process on this state file.
            with ResourceBroker(self.database).lease("web-render", {"browser": 1}, ttl=600, wait=120,
                                                     purpose="headless render"):
                final_url, html, blocked = (renderer or ctf_browser.render)(
                    response.url, allowed, cookies=browser_cookies,
                    auth_origin=config["auth_origin"], auth_generation_check=auth_generation_check)
            if not auth_generation_check():
                raise ValueError("authentication has been forgotten for this origin")
            if origin(final_url) not in allowed:
                raise ValueError("rendered page left the authorized scope")
            body = html
            response.body = html.encode()
            response.url = final_url
            rendered = {"rendered": True, "blocked_origins": blocked}
        if adapter == "rctf":
            matches = [item for item in ctf_rctf.challenges(json.loads(body))
                       if str(item.get("id")) == challenge_id]
            if len(matches) != 1:
                raise ValueError("rCTF challenge ID not found in the listing")
            challenge = matches[0]
            title = str(challenge.get("name", "CTF challenge"))[:256]
            description_html = str(challenge.get("description", ""))[:131072]
            page = Page(description_html, url)
            description = page.text or description_html
            author = challenge.get("author")
            if isinstance(author, str) and author:
                description += "\n\nAuthor: " + author[:100]
            category = ctf_rctf.CATEGORIES.get(str(challenge.get("category", "")).lower())
            categories = [category] if category else []
            raw = challenge.get("files", [])
            if not isinstance(raw, list) or len(raw) > 16 or not all(
                    isinstance(item, dict) and isinstance(item.get("url"), str) for item in raw):
                raise ValueError("invalid rCTF file list")
            files = [urllib.parse.urljoin(url, item["url"]) for item in raw]
            response.body = json.dumps(challenge).encode()
        elif adapter == "ctfd":
            payload = json.loads(body)
            if payload.get("success") is not True or not isinstance(payload.get("data"), dict):
                raise ValueError("unrecognized CTFd challenge response")
            challenge = payload["data"]
            title = str(challenge.get("name", "CTF challenge"))[:256]
            description_html = str(challenge.get("description", ""))[:131072]
            page = Page(description_html, url)
            description = page.text or description_html
            category = str(challenge.get("category", "")).lower()
            categories = [category] if category in {"web", "crypto", "rev", "pwn", "forensics", "misc"} else []
            raw_files = challenge.get("files", [])
            if not isinstance(raw_files, list) or len(raw_files) > 16 or not all(isinstance(item, str) for item in raw_files):
                raise ValueError("invalid CTFd file list")
            files = [urllib.parse.urljoin(url, item) for item in raw_files]
        else:
            page = Page(body, response.url)
            title, description = page.title or "CTF web problem", page.text
            # Only the known AlpacaHack archive layout supplies this hint. A
            # conflicting set of page links is ambiguous, not authoritative.
            host = urllib.parse.urlsplit(response.url).hostname
            declared = set(page.categories)
            categories = list(declared) if host == "alpacahack.com" and len(declared) == 1 else []
            files = [link["url"] for link in page.links if is_distribution(link, url, adapter, challenge_id)]
        links = list(page.links)
        for file_url in files:
            if not any(link["url"] == file_url for link in links):
                links.append({"url": file_url, "text": "CTF distribution file", "download": True})
        config["request_url"] = request_url
        with tempfile.TemporaryDirectory(prefix=".metis-web-stage-", dir=self.database.parent) as temporary:
            stage = Path(temporary)
            captured = stage / ("problem.json" if adapter in {"ctfd", "rctf"} else "problem.html")
            captured.write_bytes(response.body)
            captured.chmod(0o600)
            paths = [captured]
            skipped = []
            total = 0
            if download:
                for index, file_url in enumerate(dict.fromkeys(files)):
                    if index >= 16:
                        raise ValueError("more than sixteen distribution files")
                    try:
                        file_url = clean_url(file_url)
                        permitted = origin(file_url) in client.allowed
                    except ValueError:
                        permitted = False
                    if not permitted:
                        skipped.append({"url": display_url(file_url), "reason": "origin grant required"})
                        continue
                    basename = Path(urllib.parse.unquote(urllib.parse.urlsplit(file_url).path)).name
                    filename = f"{index:02d}-" + re.sub(r"[^\w.-]", "_", basename or "artifact.bin")[:40]
                    path = stage / filename
                    downloaded = None
                    failure = ""
                    for attempt in range(3):
                        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                        try:
                            with os.fdopen(descriptor, "wb") as sink:
                                downloaded = client.request(file_url, sink=sink, max_bytes=256 * 1024 * 1024,
                                                            deadline=300)
                            break
                        except TRANSIENT_DOWNLOAD_ERRORS as exc:
                            # Idempotent GET of a distribution file: retry dropped or truncated transfers.
                            downloaded, failure = None, type(exc).__name__
                            client.requests = 0
                            if attempt < 2:
                                time.sleep(2 * (attempt + 1))
                    if downloaded is None:
                        path.unlink(missing_ok=True)
                        skipped.append({"url": display_url(file_url), "reason": f"download failed ({failure})",
                                        "next": "download it in the browser, then run "
                                                "`metis codex add-file RUN_ID PATH`"})
                        continue
                    if downloaded.status != 200:
                        raise ValueError("distribution file retrieval failed")
                    total += downloaded.size
                    if total > 512 * 1024 * 1024:
                        raise ValueError("distribution files exceed total limit")
                    paths.append(path)
            evaluation = split_for(Path("writeups"), config["adapter"], config.get("challenge_id"))
            context = self.session.intake(title=title, description=description[:65_000], paths=paths,
                                           categories=categories, max_actions=120, wall_seconds=7200,
                                           evaluation_split=evaluation["split"])
        run_id = context["run_id"]
        private_storage = self._check_web_storage()
        with sqlite3.connect(self.database) as db:
            db.execute("BEGIN IMMEDIATE")
            generation_row = db.execute("SELECT generation FROM web_auth_generations WHERE origin=?",
                                        (config["auth_origin"],)).fetchone()
            generation = generation_row[0] if generation_row else 0
            initial_state = self._client_state_for_storage(
                client, config["auth_origin"], generation, private_storage=private_storage,
                cookie_epoch=self._cookie_epoch(db),
            )
            db.execute("INSERT INTO web_runs(run_id,config,state,forms,links,salt) VALUES (?,?,?,?,?,?)",
                       (run_id, json.dumps(config), json.dumps(initial_state),
                        json.dumps(page.forms), json.dumps(links), secrets.token_hex(32)))
        return {"context": context, "web": self.context(run_id)["web"],
                "downloaded_files": len(paths) - 1, "skipped_files": skipped,
                **({"render": rendered} if rendered else {}),
                "prior_knowledge": self.knowledge.search_for_run(
                    run_id, f"{title} {description[:256]}",
                    category=categories[0] if categories else None, limit=3),
                "evaluation": evaluation,
                "page_text_is_untrusted": True}

    def context(self, run_id: str) -> dict:
        config, state, forms, links, _, paused = self._load(run_id)
        with sqlite3.connect(self.database) as db:
            attempts = db.execute("SELECT verdict FROM web_attempts WHERE run_id=? ORDER BY created", (run_id,)).fetchall()
        return {"context": self.session.context(run_id), "web": {
            "adapter": config["adapter"], "page_url": display_url(config["page_url"]),
            "challenge_id": config["challenge_id"],
            "origins": config["origins"], "forms": [
                {"index": index, "action": display_url(form["action"]), "method": form["method"],
                 "fields": [{"name": field["name"], "type": field["type"], "has_default": bool(field["value"])}
                            for field in form["fields"]]} for index, form in enumerate(forms)],
            "links": [{"index": index, "url": display_url(link["url"]), "text": link["text"],
                       "in_scope": origin(link["url"]) in config["origins"]
                       if urllib.parse.urlsplit(link["url"]).scheme in {"http", "https"} else False}
                      for index, link in enumerate(links)],
            "verdicts": [row[0] for row in attempts], "paused_until": paused,
            "verification_configured": config["adapter"] in {"ctfd", "ksnctf", "rctf"}
            or bool(config.get("submission")),
            "submission_mode": ("api" if config["adapter"] in {"ctfd", "ksnctf", "rctf"} or config.get("submission")
                                else "browser" if config["auth_origin"] in BROWSER_SUBMISSION_ORIGINS
                                else "unconfigured"),
            "cookie_count": sum(len(values) for values in state.get("cookies", {}).values()),
        }}

    def grant_origin(self, run_id: str, url: str) -> dict:
        """Add a user-authorized challenge origin (e.g. the challenge's web server) to a run."""
        config, _, _, _, _, _ = self._load(run_id)
        key = origin(url)
        if key not in config["origins"]:
            if len(config["origins"]) >= 16:
                raise ValueError("too many allowed origins")
            config["origins"].append(key)
            with sqlite3.connect(self.database) as db:
                db.execute("UPDATE web_runs SET config=? WHERE run_id=?", (json.dumps(config), run_id))
        return {"run_id": run_id, "origins": config["origins"], "granted": key}

    def request(self, run_id: str, items: list[WebRequest]) -> dict:
        """Send up to 256 scoped requests in order, sharing the run's cookie jar.

        One call is one budget action. Responses are untrusted data; bodies can be
        saved as run artifacts for the static tools.
        """
        if not 1 <= len(items) <= 256:
            raise ValueError("between 1 and 256 requests per call")
        config, state, _, _, _, _ = self._load(run_id)
        prepared = []
        for item in items:
            item = WebRequest.model_validate(item.model_dump(by_alias=True))
            target = clean_url(item.url)
            if origin(target) not in config["origins"]:
                raise ValueError("origin is not granted for this run: " + origin(target))
            if item.method.upper() not in {"GET", "POST", "HEAD", "PUT", "DELETE", "PATCH", "OPTIONS"}:
                raise ValueError("unsupported HTTP method")
            pattern = re.compile(item.extract) if item.extract else None
            body, headers = item.body()
            prepared.append((item, target, pattern, body, headers))
        client = self._client(config, state)
        self.session._reserve(run_id, "scoped_web_requests", count=str(len(items)),
                              origins=",".join(sorted({origin(entry[1]) for entry in prepared}))[:200])
        results = []
        ok_count = 0
        try:
            for number, (item, target, pattern, body, headers) in enumerate(prepared):
                client.requests = 0
                entry: dict[str, Any] = {"index": number, "method": item.method.upper(), "url": display_url(target)}
                try:
                    response = client.request(target, method=item.method.upper(), body=body, headers=headers,
                                              follow_redirects=item.follow, extended=True,
                                              max_bytes=8 * 1_048_576)
                    text = response.body.decode("utf-8", errors="replace")
                    entry.update(status=response.status, final_url=display_url(response.url),
                                 headers=response.headers, length=response.size, sha256=response.sha256)
                    if item.preview:
                        entry["body"] = text[:item.preview]
                        entry["body_truncated"] = len(text) > item.preview
                    if pattern is not None:
                        entry["matches"] = [match if isinstance(match, str) else list(match)
                                            for match in pattern.findall(text)[:32]]
                    if (item.save or len(items) == 1) and response.body:
                        suffix = Path(urllib.parse.urlsplit(target).path).suffix.lower()
                        entry["artifact"] = self.session.store_artifact(
                            run_id, response.body, directory_name=".metis-web",
                            suffix=suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ".bin")
                    ok_count += 1
                except NETWORK_ERRORS as exc:
                    entry["error"] = type(exc).__name__ + ": " + str(exc)[:200]
                results.append(entry)
        finally:
            self._save_client(run_id, client)
            self.session._emit(run_id, RunStatus.OBSERVING, tool_ok=str(ok_count == len(items)).lower(),
                               requests=str(len(items)), succeeded=str(ok_count))
            self.session._emit(run_id, RunStatus.REPLANNING)
            self.session._emit(run_id, RunStatus.PLANNING)
        jar = client.export_state()["cookies"]
        cookies = {key: {cookie["name"]: cookie["value"] for cookie in values}
                   for key, values in jar.items() if key != config["auth_origin"]}
        return {"run_id": run_id, "responses": results, "cookies": cookies,
                "output_is_untrusted": True}

    def configure_form(self, run_id: str, *, form_index: int, flag_field: str,
                       selector: str, correct_text: str, incorrect_text: str) -> dict:
        config, _, forms, _, _, _ = self._load(run_id)
        with sqlite3.connect(self.database) as db:
            attempts = db.execute("SELECT COUNT(*) FROM web_attempts WHERE run_id=?", (run_id,)).fetchone()[0]
        if attempts or config["adapter"] != "html" or not 0 <= form_index < len(forms):
            raise ValueError("configure a trusted form verifier before the first submission")
        form = forms[form_index]
        if (form["method"] != "POST" or origin(form["action"]) != config["auth_origin"]
                or flag_field not in {field["name"] for field in form["fields"]}
                or not correct_text or not incorrect_text or correct_text == incorrect_text
                or max(len(correct_text), len(incorrect_text)) > 256
                or not re.fullmatch(r"[#.][A-Za-z0-9_-]{1,80}", selector)):
            raise ValueError("invalid trusted form-verdict configuration")
        config["submission"] = {"form_index": form_index, "flag_field": flag_field,
                                 "selector": selector, "correct_text": correct_text,
                                 "incorrect_text": incorrect_text,
                                 "action": clean_url(form["action"])}
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE web_runs SET config=? WHERE run_id=?", (json.dumps(config), run_id))
        return {"run_id": run_id, "verification_configured": True}

    @locked
    def prepare_browser(self, run_id: str, candidate: str) -> dict:
        """Reserve a browser send before UI interaction; unresolved sends never expire."""
        if not candidate or len(candidate.encode()) > 65_536:
            raise ValueError("invalid bounded candidate")
        config, _, _, _, salt, paused = self._load(run_id)
        if config["adapter"] != "html" or config.get("submission"):
            raise ValueError("this run has an official API/form verifier; use submit")
        if paused > time.time():
            raise ValueError("submission cooldown is active")
        digest = hmac.new(bytes.fromhex(salt), candidate.encode(), hashlib.sha256).hexdigest()
        with sqlite3.connect(self.database) as db:
            if db.execute("SELECT 1 FROM web_attempts WHERE run_id=? AND verdict='pending'", (run_id,)).fetchone():
                raise ValueError("pending browser submission; inspect official UI and attest before another send")
            if db.execute("SELECT 1 FROM web_attempts WHERE run_id=? AND digest=?", (run_id, digest)).fetchone():
                raise ValueError("identical candidate already recorded")
            used = db.execute("SELECT COALESCE(SUM(attempts),0) FROM web_attempts WHERE run_id=?", (run_id,)).fetchone()[0]
            if used >= config["max_submissions"]:
                raise ValueError("submission limit reached")
            latest = db.execute("SELECT verdict,created FROM web_attempts WHERE run_id=? ORDER BY created DESC LIMIT 1",
                                (run_id,)).fetchone()
            if latest and latest[0] == "incorrect" and not db.execute(
                "SELECT 1 FROM ctf_hypotheses WHERE run_id=? AND created>? AND status IN ('revised','rejected') LIMIT 1",
                (run_id, latest[1]),
            ).fetchone():
                raise ValueError("record an evidence-based revised hypothesis before a new candidate")
            self.session._reserve(run_id, "official_flag_submission_browser")
            db.execute("INSERT INTO web_attempts(run_id,digest,verdict,created) VALUES (?,?,'pending',?)",
                       (run_id, digest, time.time()))
        return {"run_id": run_id, "verdict": "pending", "may_send_once": True,
                "next": "submit once in the official browser UI, then attest the observed verdict"}

    @locked
    def attest(self, run_id: str, candidate: str, *, verdict: str, evidence: str) -> dict:
        """Record an official verdict that was observed in the platform's own web UI.

        For platforms where the flag is submitted by the user's logged-in browser
        (no METIS verifier). The same replay, revision and submission-cap rules as
        `submit` apply, the candidate is stored only as a salted HMAC, and the
        solve is labelled `official_browser_observed`, distinct from API verdicts.
        """
        from metis.core.ctf_knowledge import abstract_text

        if not candidate or len(candidate.encode()) > 65_536:
            raise ValueError("invalid bounded candidate")
        if verdict not in {"correct", "incorrect"}:
            raise ValueError("verdict must be correct or incorrect")
        if not 5 <= len(evidence) <= 300:
            raise ValueError("describe what the platform UI showed (5-300 characters)")
        if candidate in evidence:
            raise ValueError("evidence must not contain the candidate")
        abstract_text(evidence)
        config, _, _, _, salt, _ = self._load(run_id)
        if config["adapter"] in {"ctfd", "ksnctf", "rctf"} or config.get("submission"):
            raise ValueError("this run has an official API/form verifier; use `metis web submit`")
        fingerprint = hmac.new(bytes.fromhex(salt), candidate.encode(), hashlib.sha256).hexdigest()
        with sqlite3.connect(self.database) as db:
            existing = db.execute("SELECT verdict FROM web_attempts WHERE run_id=? AND digest=?",
                                  (run_id, fingerprint)).fetchone()
            if existing and existing[0] != "pending":
                if existing[0] != verdict:
                    raise ValueError("candidate already has a different recorded verdict")
                status = self.session.context(run_id)["status"]
                if status == RunStatus.VERIFYING.value:
                    if verdict == "correct":
                        self.session._emit(run_id, RunStatus.SOLVED, verification="official_browser_observed")
                    else:
                        self.session._emit(run_id, RunStatus.REPLANNING, reason="official_incorrect")
                        self.session._emit(run_id, RunStatus.PLANNING)
                    status = self.session.context(run_id)["status"]
                expected_status = RunStatus.SOLVED.value if verdict == "correct" else RunStatus.PLANNING.value
                if status != expected_status:
                    raise RuntimeError("recorded browser verdict disagrees with recovered run state")
                return {"run_id": run_id, "verdict": verdict, "verified": verdict == "correct",
                        "verification": "official_browser_observed", "status": status,
                        "idempotent_retry": True,
                        "next": "record the write-up" if verdict == "correct"
                                else "record a revised hypothesis; do not resubmit the same candidate"}
            prepared = existing is not None and existing[0] == "pending"
            if not prepared and db.execute(
                "SELECT 1 FROM web_attempts WHERE run_id=? AND verdict='pending'", (run_id,)
            ).fetchone():
                raise ValueError("pending browser submission belongs to a different candidate")
            if not prepared:
                raise ValueError("prepare this exact browser submission before attesting its verdict")
            latest = db.execute("SELECT verdict,created FROM web_attempts WHERE run_id=? ORDER BY created DESC LIMIT 1",
                                (run_id,)).fetchone()
            if latest and latest[0] == "incorrect" and not db.execute(
                "SELECT 1 FROM ctf_hypotheses WHERE run_id=? AND created>? AND status IN ('revised','rejected') LIMIT 1",
                (run_id, latest[1]),
            ).fetchone():
                raise ValueError("record an evidence-based revised hypothesis before recording a new candidate")
        status = self.session.context(run_id)["status"]
        if status == RunStatus.EXECUTING.value:
            self.session._emit(run_id, RunStatus.OBSERVING, evidence=evidence)
            status = RunStatus.OBSERVING.value
        if status == RunStatus.OBSERVING.value:
            self.session._emit(run_id, RunStatus.VERIFYING)
            status = RunStatus.VERIFYING.value
        if status != RunStatus.VERIFYING.value:
            raise ValueError("browser submission is not awaiting a verdict")
        with sqlite3.connect(self.database) as db:
            cursor = db.execute("UPDATE web_attempts SET verdict=?,created=? "
                                "WHERE run_id=? AND digest=? AND verdict='pending'",
                                (verdict, time.time(), run_id, fingerprint))
            if cursor.rowcount != 1:
                raise ValueError("browser reservation changed before verdict recording")
        if verdict == "correct":
            self.session._emit(run_id, RunStatus.SOLVED, verification="official_browser_observed")
        else:
            self.session._emit(run_id, RunStatus.REPLANNING, reason="official_incorrect")
            self.session._emit(run_id, RunStatus.PLANNING)
        return {"run_id": run_id, "verdict": verdict, "verified": verdict == "correct",
                "verification": "official_browser_observed",
                "status": self.session.context(run_id)["status"],
                "next": "record the write-up" if verdict == "correct"
                        else "record a revised hypothesis; do not resubmit the same candidate"}

    @locked
    def submit(self, run_id: str, candidate: str) -> dict:
        if not candidate or len(candidate.encode()) > 65_536:
            raise ValueError("invalid bounded candidate")
        config, state, _, _, salt, paused = self._load(run_id)
        if time.time() < paused:
            raise ValueError("server cooldown has not elapsed")
        if config["adapter"] == "html" and not config.get("submission"):
            raise ValueError("a trusted official verdict rule must be configured first")
        fingerprint = hmac.new(bytes.fromhex(salt), candidate.encode(), hashlib.sha256).hexdigest()
        with sqlite3.connect(self.database) as db:
            previous = db.execute("SELECT verdict FROM web_attempts WHERE run_id=? AND digest=?", (run_id, fingerprint)).fetchone()
            retryable = {"ratelimited", "authentication_required", "not_sent"}
            # ksnctf flag submissions are idempotent. A transport failure after the
            # request was reserved must remain recoverable without changing the
            # evidence-derived candidate.
            if config["adapter"] == "ksnctf":
                retryable.add("unknown")
            if previous and previous[0] not in retryable:
                raise ValueError("identical candidate already submitted; reconsider the hypothesis")
            # A send that was reserved but never got a verdict (crash/kill mid-request) may
            # have reached the server: keep it as "unknown", never as a free retry slot.
            db.execute("UPDATE web_attempts SET verdict='unknown' WHERE run_id=? AND verdict='pending' "
                       "AND created < ?", (run_id, time.time() - 120))
            if db.execute("SELECT 1 FROM web_attempts WHERE run_id=? AND verdict='pending'", (run_id,)).fetchone():
                raise ValueError("another submission for this run is still in flight")
            if db.execute("SELECT COALESCE(SUM(attempts),0) FROM web_attempts WHERE run_id=?", (run_id,)).fetchone()[0] >= config["max_submissions"]:
                raise ValueError("submission limit reached")
            latest = db.execute("SELECT verdict,created FROM web_attempts WHERE run_id=? ORDER BY created DESC LIMIT 1",
                                (run_id,)).fetchone()
            if latest and latest[0] == "incorrect" and not db.execute(
                "SELECT 1 FROM ctf_hypotheses WHERE run_id=? AND created>? AND status IN ('revised','rejected') LIMIT 1",
                (run_id, latest[1]),
            ).fetchone():
                raise ValueError("record an evidence-based revised hypothesis before submitting a new candidate")
        client = self._client(config, state)
        client._headers(config["auth_origin"], {})  # Validate missing bindings before reserving/sending.
        self.session._reserve(run_id, "official_flag_submission")
        self.session._emit(run_id, RunStatus.OBSERVING)
        self.session._emit(run_id, RunStatus.VERIFYING)
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO web_attempts(run_id,digest,verdict,created) VALUES (?,?,?,?) "
                       "ON CONFLICT(run_id,digest) DO UPDATE SET verdict='pending',created=excluded.created,attempts=web_attempts.attempts+1",
                       (run_id, fingerprint, "pending", time.time()))
        verdict, message, cooldown = "unknown", "No recognized official verdict", 0.0
        retry_seconds: float | None = None
        response = None
        submitted = False
        try:
            if config["adapter"] == "ctfd":
                submitted = True
                response = client.request(config["base_url"] + "/api/v1/challenges/attempt", method="POST",
                                          body=json.dumps({"challenge_id": config["challenge_id"], "submission": candidate}).encode(),
                                          headers={"Content-Type": "application/json"}, sensitive=True)
                payload = json.loads(response.body)
                data = payload.get("data") if isinstance(payload, dict) else None
                if isinstance(data, dict) and payload.get("success") is True:
                    reported = data.get("status")
                    if reported in {"correct", "incorrect", "already_solved", "ratelimited"}:
                        verdict = reported
                    message = str(data.get("message", verdict))
            elif config["adapter"] == "rctf":
                submitted = True
                endpoint = (config["base_url"] + "/api/v1/challs/"
                            + urllib.parse.quote(str(config["challenge_id"]), safe="") + "/submit")
                response = client.request(endpoint, method="POST",
                                          body=json.dumps({"flag": candidate}).encode(),
                                          headers={"Content-Type": "application/json"}, sensitive=True,
                                          max_bytes=65_536, follow_redirects=False)
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() == "application/json":
                    verdict, message, waited = ctf_rctf.verdict(json.loads(response.body))
                    retry_seconds = waited if verdict == "ratelimited" else None
                    if verdict == "correct" and response.status != 200:
                        verdict = "unknown"
            elif config["adapter"] == "ksnctf":
                endpoint = config["auth_origin"] + "/api/submit"
                submitted = True
                response = client.request(
                    endpoint, method="POST",
                    body=json.dumps({"id": config["challenge_id"], "flag": candidate}).encode(),
                    headers={"Content-Type": "application/json"}, sensitive=True,
                    max_bytes=16_384, follow_redirects=False,
                )
                if (response.status == 200 and response.url == endpoint
                        and response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        == "application/json"):
                    accepted = KsnctfVerdict.model_validate_json(response.body).result
                    verdict = "correct" if accepted else "incorrect"
                    message = "Official ksnctf verdict: " + verdict
            else:
                submission = config["submission"]
                fresh = client.request(config["page_url"])
                response = fresh
                if fresh.status != 200:
                    raise ValueError("cannot refresh official form")
                page = Page(fresh.body.decode(errors="replace"), fresh.url)
                index = submission["form_index"]
                if index >= len(page.forms):
                    raise ValueError("official form changed")
                form = page.forms[index]
                if clean_url(form["action"]) != submission["action"] or form["method"] != "POST":
                    raise ValueError("official submission action changed")
                values = {field["name"]: field["value"] for field in form["fields"]
                          if field["type"] in {"hidden", "submit"}}
                values[submission["flag_field"]] = candidate
                submitted = True
                response = client.request(submission["action"], method="POST",
                                          body=urllib.parse.urlencode(values).encode(),
                                          headers={"Content-Type": "application/x-www-form-urlencoded"}, sensitive=True)
                selected = Page(response.body.decode(errors="replace"), response.url).selected_text(submission["selector"])
                if selected == submission["correct_text"]:
                    verdict = "correct"
                elif selected == submission["incorrect_text"]:
                    verdict = "incorrect"
                message = selected or "Official verdict selector was missing or ambiguous"
            message = feedback_text(message, candidate, client)
        except NETWORK_ERRORS:
            verdict = "unknown" if submitted else "not_sent"
            message = "Transport, authentication or unrecognized-verdict failure; inspect before retrying"
        finally:
            if response is not None:
                if response.status == 429:
                    verdict = "ratelimited"
                elif response.status in {401, 403}:
                    verdict = "authentication_required"
                elif response.status >= 400 and verdict == "correct":
                    verdict = "unknown"
                if verdict == "ratelimited" and retry_seconds is not None:
                    cooldown = time.time() + retry_seconds
                elif verdict == "ratelimited":
                    value = response.headers.get("retry-after", "60")
                    try:
                        seconds = float(value) if value.isdigit() and len(value) <= 12 else (
                            parsedate_to_datetime(value).timestamp() - time.time())
                    except (ValueError, TypeError, OverflowError):
                        seconds = 60
                    cooldown = time.time() + max(0, seconds)
            self._save_client(run_id, client)
            with sqlite3.connect(self.database) as db:
                db.execute("UPDATE web_attempts SET verdict=?,created=? WHERE run_id=? AND digest=?",
                           (verdict, time.time(), run_id, fingerprint))
                if cooldown:
                    db.execute("UPDATE web_runs SET paused_until=? WHERE run_id=?", (cooldown, run_id))
        if verdict == "correct":
            self.session._emit(run_id, RunStatus.SOLVED, verification="official_" + config["adapter"])
        elif verdict == "already_solved":
            self.session._emit(run_id, RunStatus.EXHAUSTED, reason="official_already_solved")
        else:
            self.session._emit(run_id, RunStatus.REPLANNING, reason="official_" + verdict)
            self.session._emit(run_id, RunStatus.PLANNING)
        return {"run_id": run_id, "verdict": verdict, "verified": verdict == "correct",
                "feedback": message, "status": self.session.context(run_id)["status"],
                "next": "record the successful technique" if verdict == "correct"
                        else "inspect feedback and revise the hypothesis; do not repeat the same candidate"}
