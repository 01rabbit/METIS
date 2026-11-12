"""Scoped URL intake and official CTFd, ksnctf and configured-form verdicts."""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import re
import secrets
import sqlite3
import tempfile
import time
import urllib.parse
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from metis.core.codex_session import CodexSession
from metis.core.contracts import RunStatus
from metis.core.ctf_html import Page, display_url
from metis.core.ctf_http import SafeHTTP, clean_url, origin
from metis.core.ctf_knowledge import KnowledgeBase
from metis.core.ctf_ksnctf import KsnctfVerdict, is_official_problem, problem_id

NETWORK_ERRORS = (OSError, ValueError, KeyError, TypeError, RuntimeError, http.client.HTTPException)
ATTACHMENTS = {".zip", ".tar", ".gz", ".xz", ".bz2", ".7z", ".rar", ".bin", ".elf", ".exe",
               ".png", ".jpg", ".jpeg", ".wav", ".pcap", ".pcapng", ".pdf", ".txt", ".c", ".cpp", ".py", ".class", ".jar"}


def feedback_text(value: str, candidate: str, client: SafeHTTP) -> str:
    for secret in [candidate, *client.secret_values()]:
        if secret:
            value = value.replace(secret, "[redacted]")
    value = re.sub(r"(?:FLAG|flag)_[^\s<>\"']{1,200}|[A-Za-z0-9_]{1,32}\{[^{}\r\n]{1,200}\}",
                   "[candidate redacted]", value)
    return value[:512]


class WebWorkflow:
    def __init__(self, database: Path):
        self.session = CodexSession(database)
        self.database = database
        self.knowledge = KnowledgeBase(database)
        with sqlite3.connect(database) as db:
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

    def auth(self, url: str, *, kind: str, value: str, scheme: str = "Token") -> dict:
        key = origin(url)
        if kind not in {"token", "cookie"} or not value or len(value) > 16384 or any(char in value for char in "\r\n"):
            raise ValueError("invalid private CTF credential")
        if scheme not in {"Token", "Bearer"}:
            raise ValueError("invalid credential scheme")
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT payload FROM web_credentials WHERE origin=?", (key,)).fetchone()
            values = json.loads(row[0]) if row else {}
            values[kind] = value
            values["scheme"] = scheme
            db.execute("INSERT INTO web_credentials(origin,payload) VALUES (?,?) "
                       "ON CONFLICT(origin) DO UPDATE SET payload=excluded.payload", (key, json.dumps(values)))
        return {"origin": key, "credential_stored": True, "kind": kind,
                "storage": "private local state; excluded from Git"}

    def _load(self, run_id: str) -> tuple[dict, dict, list, list, str, float]:
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT config,state,forms,links,salt,paused_until FROM web_runs WHERE run_id=?",
                             (run_id,)).fetchone()
        if row is None:
            raise ValueError("web workflow not found")
        return json.loads(row[0]), json.loads(row[1]), json.loads(row[2]), json.loads(row[3]), row[4], row[5]

    def _client(self, config: dict, state: dict) -> SafeHTTP:
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT payload FROM web_credentials WHERE origin=?",
                             (config["auth_origin"],)).fetchone()
        return SafeHTTP(config["origins"], auth_origin=config["auth_origin"],
                        token_env=config.get("token_env"), cookie_env=config.get("cookie_env"),
                        state=state, credentials=json.loads(row[0]) if row else {}, timeout=15)

    def _save_client(self, run_id: str, client: SafeHTTP) -> None:
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE web_runs SET state=? WHERE run_id=?",
                       (json.dumps(client.export_state()), run_id))

    def open(self, url: str, *, adapter: str = "auto", challenge_id: int | None = None,
             allowed_origins: list[str] | None = None, token_env: str | None = None,
             cookie_env: str | None = None, download: bool = True) -> dict:
        url = clean_url(url)
        if adapter == "auto":
            adapter = "ksnctf" if is_official_problem(url) else "html"
        if adapter not in {"html", "ctfd", "ksnctf"}:
            raise ValueError("adapter must be auto, html, ctfd or ksnctf")
        if adapter == "ksnctf":
            inferred_id = problem_id(url)
            if challenge_id is not None and challenge_id != inferred_id:
                raise ValueError("ksnctf challenge ID does not match the problem URL")
            challenge_id = inferred_id
        allowed = list(dict.fromkeys([origin(url), *[origin(item) for item in allowed_origins or []]]))
        if len(allowed) > 16:
            raise ValueError("too many allowed origins")
        config: dict[str, Any] = {"page_url": url, "adapter": adapter, "origins": allowed,
                  "auth_origin": origin(url), "token_env": token_env, "cookie_env": cookie_env,
                  "challenge_id": challenge_id, "max_submissions": 10}
        client = self._client(config, {})
        request_url = url
        if adapter == "ctfd":
            if challenge_id is None or not 1 <= challenge_id <= 1_000_000:
                raise ValueError("CTFd challenge ID is required")
            config["base_url"] = url.rstrip("/")
            request_url = config["base_url"] + "/api/v1/challenges/" + str(challenge_id)
        response = client.request(request_url)
        if response.status != 200:
            raise ValueError("problem retrieval failed; check URL and CTF authentication")
        if adapter == "ksnctf" and (
            origin(response.url) != origin(url) or problem_id(response.url) != challenge_id
        ):
            raise ValueError("ksnctf problem retrieval redirected to another problem or origin")
        body = response.body.decode("utf-8", errors="replace")
        files = []
        if adapter == "ctfd":
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
            title, description, categories = page.title or "CTF web problem", page.text, []
            files = [link["url"] for link in page.links if link["download"] or
                     Path(urllib.parse.urlsplit(link["url"]).path).suffix.lower() in ATTACHMENTS]
        links = list(page.links)
        for file_url in files:
            if not any(link["url"] == file_url for link in links):
                links.append({"url": file_url, "text": "CTF distribution file", "download": True})
        config["request_url"] = request_url
        with tempfile.TemporaryDirectory(prefix=".metis-web-stage-", dir=self.database.parent) as temporary:
            stage = Path(temporary)
            captured = stage / ("problem.json" if adapter == "ctfd" else "problem.html")
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
                    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, "wb") as sink:
                        downloaded = client.request(file_url, sink=sink, max_bytes=256 * 1024 * 1024)
                    if downloaded.status != 200:
                        raise ValueError("distribution file retrieval failed")
                    total += downloaded.size
                    if total > 512 * 1024 * 1024:
                        raise ValueError("distribution files exceed total limit")
                    paths.append(path)
            context = self.session.intake(title=title, description=description[:65_000], paths=paths,
                                           categories=categories, max_actions=120, wall_seconds=7200)
        run_id = context["run_id"]
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO web_runs(run_id,config,state,forms,links,salt) VALUES (?,?,?,?,?,?)",
                       (run_id, json.dumps(config), json.dumps(client.export_state()),
                        json.dumps(page.forms), json.dumps(links), secrets.token_hex(32)))
        return {"context": context, "web": self.context(run_id)["web"],
                "downloaded_files": len(paths) - 1, "skipped_files": skipped,
                "prior_knowledge": self.knowledge.search(description[:256],
                                                          category=categories[0] if categories else None, limit=3),
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
            "verification_configured": config["adapter"] in {"ctfd", "ksnctf"} or bool(config.get("submission")),
            "cookie_count": sum(len(values) for values in state.get("cookies", {}).values()),
        }}

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
            if previous and previous[0] not in {"ratelimited", "authentication_required", "not_sent"}:
                raise ValueError("identical candidate already submitted; reconsider the hypothesis")
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
                if verdict == "ratelimited":
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
