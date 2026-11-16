"""Start screen for `./play` (curses, stdlib only).

Layout ideas taken from tools people already know:
  * banner + version + one-line inventory (Metasploit, sqlmap)
  * list pane + detail pane, selection highlight (lazygit, k9s)
  * rounded boxes and block progress bars (btop)
  * reverse-video key bar at the bottom (htop, k9s)

`compose()` builds the whole screen as draw operations, so it is testable without a
terminal; `run()` is the curses loop around it.
"""
from __future__ import annotations

import contextlib
import importlib.metadata
import shutil
import subprocess
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOGO = [
    "███╗   ███╗███████╗████████╗██╗███████╗",
    "████╗ ████║██╔════╝╚══██╔══╝██║██╔════╝",
    "██╔████╔██║█████╗     ██║   ██║███████╗",
    "██║╚██╔╝██║██╔══╝     ██║   ██║╚════██║",
    "██║ ╚═╝ ██║███████╗   ██║   ██║███████║",
    "╚═╝     ╚═╝╚══════╝   ╚═╝   ╚═╝╚══════╝",
]
# Identity and slogan from docs/MASTER_IMPLEMENTATION.md.
TAGLINE = "Autonomous Adversarial Problem-Solving Intelligence"
SLOGAN = "Observe · Reason · Exploit · Evolve"
NEW_ITEM = "__new__"
MAX_WORKERS = 16

Op = tuple[int, int, str, str]  # row, column, text, style


# -- text width (Japanese is two cells wide) ------------------------------------------
def cells(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def fit(text: str, width: int) -> str:
    """Cut to at most ``width`` cells, with an ellipsis when cut."""
    if width <= 0:
        return ""
    if cells(text) <= width:
        return text
    out, used = "", 0
    for char in text:
        size = 2 if unicodedata.east_asian_width(char) in "WF" else 1
        if used + size > width - 1:
            break
        out += char
        used += size
    return out + "…"


def pad(text: str, width: int) -> str:
    text = fit(text, width)
    return text + " " * (width - cells(text))


def wrap(text: str, width: int) -> list[str]:
    """Split into lines of at most ``width`` cells (character based, for mixed Japanese text)."""
    lines, current = [], ""
    for char in text:
        if cells(current + char) > width:
            lines.append(current)
            current = char.lstrip() if char == " " else char
        else:
            current += char
    return [*lines, current] if current or not lines else lines


def bar(ratio: float, width: int) -> str:
    filled = round(max(0.0, min(1.0, ratio)) * width)
    return "█" * filled + "░" * (width - filled)


# -- data --------------------------------------------------------------------------------
@dataclass
class Inventory:
    version: str = "dev"
    revision: str = ""
    tools: dict[str, bool] = field(default_factory=dict)
    sandbox: bool | None = None  # None while the check is still running
    techniques: int = 0
    contests: list[dict[str, Any]] = field(default_factory=list)


def _revision(root: Path) -> str:
    try:
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True, timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def gather(database: Path, root: Path) -> Inventory:
    import sqlite3

    from metis.core.ctf_contest import ContestBoard
    from metis.core.ctf_contest_ops import contest_info_report
    from metis.core.ctf_swarm import session_name, tmux_windows

    try:
        version = importlib.metadata.version("metis-ctf")
    except importlib.metadata.PackageNotFoundError:
        version = "dev"
    board = ContestBoard(database)
    has_tmux = shutil.which("tmux") is not None
    contests = []
    for item in board.contests():
        info = contest_info_report(database, item["contest_id"])
        running = has_tmux and tmux_windows(session_name(item["contest_id"])) is not None
        contests.append({**info, "running": running})
    techniques = 0
    try:
        with sqlite3.connect(database) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='munin_cards'").fetchone():
                techniques = db.execute("SELECT COUNT(*) FROM munin_cards").fetchone()[0]
    except sqlite3.Error:
        pass
    return Inventory(version=version, revision=_revision(root),
                     tools={"claude": shutil.which("claude") is not None, "tmux": has_tmux},
                     techniques=techniques, contests=contests)


# -- screen composition -----------------------------------------------------------------
def _box(ops: list[Op], top: int, left: int, height: int, width: int, title: str, style: str = "border") -> None:
    if height < 2 or width < 4:
        return
    label = f" {fit(title, width - 6)} " if title else ""
    ops.append((top, left, "╭─" + label + "─" * max(0, width - 3 - cells(label)) + "╮", style))
    if label:
        ops.append((top, left + 2, label, "title"))
    for row in range(1, height - 1):
        ops.append((top + row, left, "│", style))
        ops.append((top + row, left + width - 1, "│", style))
    ops.append((top + height - 1, left, "╰" + "─" * (width - 2) + "╯", style))


def _detail(item: dict[str, Any] | None, width: int, workers: int) -> list[tuple[str, str]]:
    if item is None:
        return [("新しい大会を登録します。", "title"), ("", "normal"),
                ("問題一覧の URL を入力すると、サイトの種類を判定して", "normal"),
                ("既定のルールでボードを作り、Claude Code が", "normal"),
                ("ルール確認と問題の取り込みから始めます。", "normal"), ("", "normal"),
                ("対応: AlpacaHack · ksnctf · CTFd · rCTF", "accent"),
                ("その他のサイトは Claude がページを読んで登録", "dim")]
    counts = item["counts"]
    total = item["total"] or 0
    solved = counts.get("solved", 0)
    ratio = solved / total if total else 0.0
    gauge = max(10, width - 16)
    lines = [(f"{item['platform']}  ·  {item['url'] or 'URL 未登録'}", "dim"), ("", "normal"),
             (f"{bar(ratio, gauge)} {ratio:4.0%}", "ok" if ratio >= 1 else "accent"),
             (f"{solved}/{total} solved   {item['score']:g} pts", "normal"), ("", "normal")]
    chips = [("✔ solved", "solved", "ok"), ("▶ working", "investigating", "accent"), ("… queued", "queued", "normal"),
             ("⇄ handoff", "handoff", "warn"), ("✖ blocked", "blocked", "bad")]
    for label, key, style in chips:
        if counts.get(key) or key in {"solved", "queued"}:
            lines.append((f"{label:<11}{counts.get(key, 0):>4}", style if counts.get(key) else "dim"))
    refreshed = item["last_refresh"] or "未実施"
    lines.append(("", "normal"))
    lines.append(("● tmux で実行中  ⏎ で再接続", "ok") if item["running"] else
                 (f"○ 停止中  ⏎ で開始（ワーカー {workers} 台）", "dim"))
    if counts.get("handoff"):
        lines.append((f"⇄ 引き継ぎ待ち {counts['handoff']} 問 ─ Claude が最初に処理します", "warn"))
    lines.append((f"新着確認: {refreshed}", "dim"))
    lines.append(("", "normal"))
    lines.append(("ルール" + ("" if item["configured"] else "（推定・未保存）"), "title"))
    for text in item["rules_text"]:
        lines.extend((" " + part, "normal") for part in wrap(text, width - 2))
    return lines


def compose(inventory: Inventory, selected: int, workers: int, width: int, height: int,
            message: str = "", now: float | None = None) -> list[Op]:
    ops: list[Op] = []
    items: list[dict[str, Any] | None] = [*inventory.contests, None]
    selected = max(0, min(selected, len(items) - 1))
    compact = height < 22 or width < 72
    row = 0
    if compact:
        ops.append((0, 1, "◆ METIS", "logo0"))
        ops.append((0, 9, fit(SLOGAN, width - 10), "dim"))
        row = 1
    else:
        indent = max(1, (width - cells(LOGO[0])) // 2)
        for index, line in enumerate(LOGO):
            ops.append((index, indent, line, f"logo{index}"))
        ops.append((len(LOGO), max(1, (width - cells(TAGLINE)) // 2), TAGLINE, "title"))
        ops.append((len(LOGO) + 1, max(1, (width - cells(SLOGAN)) // 2), SLOGAN, "accent"))
        row = len(LOGO) + 2
    # status line: version, tools, inventory, clock
    version = f"v{inventory.version}" + (f" · {inventory.revision}" if inventory.revision else "")
    x = 1
    for text, style in [(version, "accent"), ("   ", "normal")] + [
            (f"{name} {'●' if ok else '○'}  ", "ok" if ok else "bad") for name, ok in inventory.tools.items()] + [
            ("sandbox " + ("…" if inventory.sandbox is None else "●" if inventory.sandbox else "○") + "  ",
             "dim" if inventory.sandbox is None else "ok" if inventory.sandbox else "warn")]:
        ops.append((row, x, fit(text, max(0, width - x - 1)), style))
        x += cells(text)
    solved = sum(item["counts"].get("solved", 0) for item in inventory.contests)
    summary = f"{len(inventory.contests)} contests · {solved} solved · MUNIN {inventory.techniques} cards"
    clock = time.strftime("%Y-%m-%d %H:%M", time.localtime(now or time.time()))
    right = f"{summary}   {clock}"
    if x + cells(right) + 2 < width:
        ops.append((row, width - cells(right) - 1, right, "dim"))
    row += 2
    body = height - row - 2
    list_width = min(40, max(28, width * 2 // 5)) if not compact else width - 2
    if body >= 4:
        _box(ops, row, 0, body, list_width, "Contests")
        visible = body - 2
        start = max(0, selected - visible + 1)
        for offset, item in enumerate(items[start:start + visible]):
            index = start + offset
            marker = "▶ " if index == selected else "  "
            if item is None:
                text, tail, style = "+ 新しい大会", "", "accent"
            else:
                text = item["name"]
                tail = f"{item['counts'].get('solved', 0)}/{item['total']}" + (" ●" if item["running"] else "  ")
                style = "normal"
                if item["counts"].get("handoff"):
                    tail = f"⇄{item['counts']['handoff']}  " + tail
            inner = list_width - 4
            line = pad(marker + text, inner - cells(tail)) + tail
            ops.append((row + 1 + offset, 2, line, "sel" if index == selected else style))
        hints = ["⏎ 再開: 新着確認→状況報告→引き継ぎ", "←→ で並列ワーカー台数を選ぶ"]
        free = visible - min(len(items), visible)
        for offset, hint in enumerate(hints[-free:] if free > 1 else []):
            ops.append((row + body - 1 - min(free, len(hints)) + offset, 2, fit(hint, list_width - 4), "dim"))
        if not compact:
            left = list_width + 1
            detail_width = width - left - 1
            current = items[selected]
            _box(ops, row, left, body, detail_width, current["name"] if current else "New contest")
            for offset, (text, style) in enumerate(_detail(current, detail_width - 4, workers)[:body - 2]):
                ops.append((row + 1 + offset, left + 2, fit(text, detail_width - 4), style))
    # message line and key bar
    if message:
        ops.append((height - 2, 1, fit(message, width - 2), "warn"))
    x = 0
    for key, label in (("↑↓", "選択"), ("⏎", "開く"), ("n", "新規"), ("←→", f"ワーカー {workers}"),
                       ("r", "更新"), ("q", "終了")):
        chunk_key, chunk_label = f" {key} ", f" {label} "
        if x + cells(chunk_key) + cells(chunk_label) >= width:
            break
        ops.append((height - 1, x, chunk_key, "key"))
        ops.append((height - 1, x + cells(chunk_key), chunk_label, "keylabel"))
        x += cells(chunk_key) + cells(chunk_label) + 1
    return ops


# -- curses loop -------------------------------------------------------------------------
def _styles(curses: Any) -> dict[str, int]:
    styles = {name: 0 for name in ("normal", "border", "dim", "title", "accent", "ok", "warn", "bad", "keylabel")}
    styles["sel"] = curses.A_REVERSE | curses.A_BOLD
    styles["key"] = curses.A_REVERSE
    styles["title"] = curses.A_BOLD
    for index in range(len(LOGO)):
        styles[f"logo{index}"] = curses.A_BOLD
    if not curses.has_colors():
        return styles
    curses.start_color()
    curses.use_default_colors()
    rich = curses.COLORS >= 256
    gradient = [51, 45, 39, 33, 63, 99] if rich else [curses.COLOR_CYAN] * 3 + [curses.COLOR_BLUE] * 2 + [
        curses.COLOR_MAGENTA]
    palette = {"border": 60 if rich else curses.COLOR_BLUE, "dim": 245 if rich else curses.COLOR_WHITE,
               "title": 255 if rich else curses.COLOR_WHITE, "accent": 45 if rich else curses.COLOR_CYAN,
               "ok": 78 if rich else curses.COLOR_GREEN, "warn": 214 if rich else curses.COLOR_YELLOW,
               "bad": 203 if rich else curses.COLOR_RED, "keylabel": 250 if rich else curses.COLOR_WHITE}
    pair = 1
    for index, colour in enumerate(gradient):
        curses.init_pair(pair, colour, -1)
        styles[f"logo{index}"] = curses.color_pair(pair) | curses.A_BOLD
        pair += 1
    for name, colour in palette.items():
        curses.init_pair(pair, colour, -1)
        styles[name] = curses.color_pair(pair) | (curses.A_BOLD if name == "title" else 0)
        pair += 1
    curses.init_pair(pair, 16 if rich else curses.COLOR_BLACK, 45 if rich else curses.COLOR_CYAN)
    styles["key"] = curses.color_pair(pair) | curses.A_BOLD
    curses.init_pair(pair + 1, 16 if rich else curses.COLOR_BLACK, 45 if rich else curses.COLOR_CYAN)
    styles["sel"] = curses.color_pair(pair + 1) | curses.A_BOLD
    return styles


def _paint(screen: Any, ops: list[Op], styles: dict[str, int]) -> None:
    height, width = screen.getmaxyx()
    screen.erase()
    for row, column, text, style in ops:
        if 0 <= row < height and 0 <= column < width:
            with contextlib.suppress(Exception):  # writing the last cell raises in curses
                screen.addstr(row, column, fit(text, width - column - (1 if row == height - 1 else 0)),
                              styles.get(style, 0))
    screen.refresh()


def _read_line(screen: Any, curses: Any, styles: dict[str, int], label: str) -> str | None:
    """One-line input box at the bottom (handles Japanese via get_wch). Esc cancels."""
    height, width = screen.getmaxyx()
    text = ""
    curses.curs_set(1)
    try:
        while True:
            screen.move(height - 2, 0)
            screen.clrtoeol()
            prompt = f" {label} › "
            screen.addstr(height - 2, 0, fit(prompt, width - 1), styles["accent"])
            shown = text[-max(1, width - cells(prompt) - 2):]
            screen.addstr(height - 2, min(width - 2, cells(prompt)), fit(shown, width - cells(prompt) - 1),
                          styles["title"])
            screen.refresh()
            try:
                key = screen.get_wch()
            except curses.error:  # input timeout of the main loop; keep waiting
                continue
            if key in ("\n", "\r", curses.KEY_ENTER):
                return text.strip()
            if key == "\x1b":
                return None
            if key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                text = text[:-1]
            elif isinstance(key, str) and key.isprintable():
                text += key
    finally:
        curses.curs_set(0)


def run(database: Path, root: Path, *, workers: int = 0) -> dict[str, Any] | None:  # pragma: no cover
    """Show the start screen. Returns {"contest_id", "new", "workers"} or None."""
    import curses
    import locale

    from metis.core.ctf_contest import ContestBoard
    from metis.core.ctf_sandbox import status as sandbox_status

    locale.setlocale(locale.LC_ALL, "")
    inventory = gather(database, root)

    def check_sandbox() -> None:
        try:
            state = sandbox_status(database)
            inventory.sandbox = bool(state["configured"] and state["engine_available"])
        except Exception:  # noqa: BLE001 -- the start screen must not fail on a sandbox probe
            inventory.sandbox = False

    threading.Thread(target=check_sandbox, daemon=True).start()

    def loop(screen: Any) -> dict[str, Any] | None:
        nonlocal inventory, workers
        curses.curs_set(0)
        screen.keypad(True)
        screen.timeout(500)
        styles = _styles(curses)
        selected, message = 0, ""
        while True:
            height, width = screen.getmaxyx()
            if height < 12 or width < 40:
                screen.erase()
                screen.addstr(0, 0, fit("ターミナルを広げてください（40x12 以上）", width - 1))
                screen.refresh()
            else:
                _paint(screen, compose(inventory, selected, workers, width, height, message), styles)
            try:
                key = screen.get_wch()
            except curses.error:
                continue
            count = len(inventory.contests) + 1
            message = ""
            if key in (curses.KEY_UP, "k"):
                selected = (selected - 1) % count
            elif key in (curses.KEY_DOWN, "j", "\t"):
                selected = (selected + 1) % count
            elif key in (curses.KEY_RIGHT, "l", "+"):
                workers = min(MAX_WORKERS, workers + 1)
            elif key in (curses.KEY_LEFT, "h", "-"):
                workers = max(0, workers - 1)
            elif key in ("q", "Q", "\x1b"):
                return None
            elif key in ("r", "R"):
                sandbox = inventory.sandbox
                inventory = gather(database, root)
                inventory.sandbox = sandbox
                message = "更新しました"
            elif key in ("n", "N") or (key in ("\n", "\r", curses.KEY_ENTER) and selected == count - 1):
                url = _read_line(screen, curses, styles, "問題一覧の URL")
                if not url:
                    continue
                name = _read_line(screen, curses, styles, "大会名（空欄ならホスト名）")
                if name is None:
                    continue
                try:
                    created = ContestBoard(database).new(url, name or None)
                except ValueError as exc:
                    message = f"登録できません: {exc}"
                    continue
                return {"contest_id": created["contest_id"], "new": True, "workers": workers}
            elif key in ("\n", "\r", curses.KEY_ENTER):
                return {"contest_id": inventory.contests[selected]["contest_id"], "new": False, "workers": workers}

    return curses.wrapper(loop)


def banner_text(inventory: Inventory) -> str:
    """Plain banner for non-interactive output (pipes, --plain)."""
    version = f"v{inventory.version}" + (f" ({inventory.revision})" if inventory.revision else "")
    return "\n".join([*LOGO, TAGLINE, f"{SLOGAN}   {version}", ""])
