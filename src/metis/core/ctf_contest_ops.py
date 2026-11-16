"""Contest operations that combine the board with the network or other stores."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from metis.core.ctf_contest import ContestBoard
from metis.core.ctf_platforms import PLATFORMS, describe_rules

LISTING_SHAPE = ('[{"challenge_id": "slug-or-number", "title": "...", "category": "pwn|rev|web|crypto|misc|forensics", '
                 '"points": 100, "solves": 12, "url": "https://.../challenge-page", "adapter": "html"}]')


def contest_refresh(database: Path, contest_id: str, *, listing_file: Path | None = None,
                    token_env: str | None = None, cookie_env: str | None = None) -> dict[str, Any]:
    board = ContestBoard(database)
    meta = board.meta(contest_id)
    if listing_file is not None:
        raw = listing_file.read_bytes()
        if len(raw) > 1_048_576:
            raise ValueError("listing file exceeds 1 MiB")
        payload = json.loads(raw)
        listing = payload.get("challenges") if isinstance(payload, dict) else payload
        if not isinstance(listing, list):
            raise ValueError("listing file must hold a JSON array (or {\"challenges\": [...]})")
        return {**board.refresh(contest_id, listing), "source": "file"}
    if meta["catalog"] in {"ctfd", "rctf"} and meta["url"]:
        from metis.core.ctf_web import WebWorkflow

        catalog = WebWorkflow(database).catalog(meta["url"], adapter=meta["catalog"], token_env=token_env,
                                                cookie_env=cookie_env)
        return {**board.refresh(contest_id, catalog["challenges"]), "source": meta["catalog"]}
    hint = PLATFORMS.get(meta["platform"], {}).get(
        "list_hint", "問題一覧ページ（必要ならブラウザ）を読み、問題ごとの URL と ID を集める")
    return {"contest_id": contest_id, "source": "agent", "added": [], "needs_listing": True,
            "next": "一覧を読み、ボードに無い問題を含む JSON 配列をファイルに書いて "
                    f"`metis contest refresh {contest_id} --file FILE` を実行する（既存の問題は状態を変えずに残る）",
            "how": hint, "shape": LISTING_SHAPE, "list_url": meta["url"]}


def contest_info_report(database: Path, contest_id: str) -> dict[str, Any]:
    board = ContestBoard(database)
    meta = board.meta(contest_id)
    state = board.board(contest_id)
    counts = {key: value for key, value in state["counts"].items() if value}
    pending = [{"challenge_id": item["challenge_id"], "title": item["title"], "state": item["state"],
                "note": item.get("notes")}
               for item in state["challenges"] if item["state"] in {"handoff", "candidate", "blocked"}]
    refreshed = meta["refreshed"]
    return {"contest_id": contest_id, "name": state["name"], "platform": meta["platform"], "url": meta["url"],
            "catalog": meta["catalog"], "configured": meta["configured"], "rules": meta["rules"],
            "rules_text": describe_rules(meta["rules"]), "score": state["score"],
            "total": len(state["challenges"]), "counts": counts, "attention": pending,
            "last_refresh": time.strftime("%Y-%m-%d %H:%M", time.localtime(refreshed)) if refreshed else None}
