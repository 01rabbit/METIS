"""rCTF (redpwn) API contract: challenge listing and strict submission verdicts.

rCTF serves every challenge from ``GET /api/v1/challs`` and accepts flags at
``POST /api/v1/challs/{id}/submit``. Authentication is a Bearer auth token,
derived from a team token through ``POST /api/v1/auth/login``.
"""
from __future__ import annotations

import re
from typing import Any

VERDICTS = {
    "goodFlag": "correct",
    "badFlag": "incorrect",
    "badAlreadySolvedChallenge": "already_solved",
    "badRateLimit": "ratelimited",
    "badToken": "authentication_required",
    "badNotStarted": "unknown",
    "badEnded": "unknown",
}
CATEGORIES = {"web": "web", "crypto": "crypto", "rev": "rev", "reversing": "rev", "pwn": "pwn",
              "forensics": "forensics", "misc": "misc"}


def challenge_key(value: Any) -> str:
    text = str(value)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", text):
        raise ValueError("invalid rCTF challenge ID")
    return text


def challenges(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("kind") != "goodChallenges":
        raise ValueError("unrecognized rCTF challenge listing")
    items = payload.get("data")
    if not isinstance(items, list) or len(items) > 500 or not all(isinstance(item, dict) for item in items):
        raise ValueError("invalid rCTF challenge listing")
    return items


def verdict(payload: Any) -> tuple[str, str, float]:
    """Return (verdict, message, retry_seconds) from a submission response body."""
    if not isinstance(payload, dict) or not isinstance(payload.get("kind"), str):
        return "unknown", "No recognized rCTF verdict", 0.0
    kind = payload["kind"]
    result = VERDICTS.get(kind, "unknown")
    retry = 0.0
    data = payload.get("data")
    if result == "ratelimited" and isinstance(data, dict) and isinstance(data.get("timeLeft"), (int, float)):
        retry = max(0.0, min(float(data["timeLeft"]) / 1000, 3600.0))
    return result, str(payload.get("message", kind))[:256], retry
