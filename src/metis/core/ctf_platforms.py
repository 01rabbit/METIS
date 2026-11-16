"""Known CTF platforms: how to list challenges and the default rules METIS must respect.

A contest records its platform, URL and rules once (``metis contest configure``). The
launcher and every agent prompt read them back, so per-site constraints such as
"submit through the browser form" or "one instance per account" are not re-learned
each session. Rules are defaults for the operator to confirm, not legal advice.
"""
from __future__ import annotations

import urllib.parse
from typing import Any

# catalog: how new challenges are found.
#   ctfd / rctf -> METIS reads the platform API (`metis contest refresh`)
#   agent       -> the operator's Claude session reads the list page (often in the browser)
#                  and passes the entries to `metis contest refresh --file`
PLATFORMS: dict[str, dict[str, Any]] = {
    "alpacahack": {
        "hosts": {"alpacahack.com"},
        "list_url": "https://alpacahack.com/daily",
        "adapter": "html",
        "catalog": "agent",
        "list_hint": "https://alpacahack.com/daily などの一覧をブラウザで開き、問題ページの URL から ID（スラッグ）を取る",
        "rules": {
            "submission": "browser",
            "instance_limit": 1,
            "writeup_publish": "after_end",
            "notes": ("提出はブラウザのフォームから（公式APIへの直接アクセスは規約で禁止）。"
                      "アカウント共有禁止。解法の公開は各問題の期間終了後のみ。"),
        },
    },
    "ksnctf": {
        "hosts": {"ksnctf.sweetduet.info"},
        "list_url": "https://ksnctf.sweetduet.info/",
        "adapter": "ksnctf",
        "catalog": "agent",
        "list_hint": "トップページの問題一覧を読み、番号を ID、URL を https://ksnctf.sweetduet.info/problem/<番号> にする",
        "rules": {"submission": "api", "instance_limit": None, "writeup_publish": "unknown", "notes": ""},
    },
}
GENERIC_RULES = {"submission": "unknown", "instance_limit": None, "writeup_publish": "unknown", "notes": ""}
RULE_KEYS = {"submission", "instance_limit", "writeup_publish", "notes", "ends_at", "starts_at"}
SUBMISSION = {"api", "browser", "unknown"}
PUBLISH = {"anytime", "after_end", "never", "unknown"}


def detect(url: str) -> dict[str, Any]:
    """Platform guess from the URL alone (no network)."""
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("contest URL must be http(s)")
    host = parts.hostname.lower()
    for name, spec in PLATFORMS.items():
        if host in spec["hosts"] or any(host.endswith("." + item) for item in spec["hosts"]):
            return {"platform": name, "url": url.strip(), "adapter": spec["adapter"], "catalog": spec["catalog"],
                    "rules": dict(spec["rules"]), "list_hint": spec["list_hint"]}
    # Unknown host: CTFd or rCTF are probed later; until then the agent reads the page.
    return {"platform": "unknown", "url": url.strip(), "adapter": "auto", "catalog": "agent",
            "rules": dict(GENERIC_RULES),
            "list_hint": "`metis web catalog URL --adapter ctfd` か `--adapter rctf` で読めればそれを使う。"
                         "読めなければブラウザで一覧を開く"}


def validate_rules(rules: dict[str, Any]) -> dict[str, Any]:
    unknown = set(rules) - RULE_KEYS
    if unknown:
        raise ValueError("unsupported rule fields: " + ", ".join(sorted(unknown)))
    if "submission" in rules and rules["submission"] not in SUBMISSION:
        raise ValueError("submission must be api, browser or unknown")
    if "writeup_publish" in rules and rules["writeup_publish"] not in PUBLISH:
        raise ValueError("writeup_publish must be anytime, after_end, never or unknown")
    limit = rules.get("instance_limit")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 64):
        raise ValueError("instance_limit must be null or 1..64")
    for key in ("notes", "ends_at", "starts_at"):
        if key in rules and rules[key] is not None and (not isinstance(rules[key], str) or len(rules[key]) > 1000):
            raise ValueError(f"{key} must be text up to 1000 characters")
    return rules


def describe_rules(rules: dict[str, Any]) -> list[str]:
    labels = {"api": "METIS から API で提出（metis web submit）", "browser": "ブラウザのフォームで提出し metis web attest",
              "unknown": "未確認（最初に確認する）"}
    publish = {"anytime": "いつでも可", "after_end": "期間終了後のみ", "never": "公開しない", "unknown": "未確認"}
    lines = [f"提出方法: {labels.get(rules.get('submission', 'unknown'), '未確認')}",
             f"インスタンス同時起動数: {rules.get('instance_limit') or '制限なし/未確認'}",
             f"WriteUP 公開: {publish.get(rules.get('writeup_publish', 'unknown'), '未確認')}"]
    for key, label in (("starts_at", "開始"), ("ends_at", "終了")):
        if rules.get(key):
            lines.append(f"{label}: {rules[key]}")
    if rules.get("notes"):
        lines.append("注意: " + rules["notes"])
    return lines
