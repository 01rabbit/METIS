"""Terminal dashboard for a running swarm (`metis swarm watch`).

Pure-stdlib curses UI that refreshes from METIS state every few seconds:
score and counts, one line per worker with what it is doing right now, the
challenge table with coloured states, and recent swarm events. `render()` builds
the screen as plain lines so it is testable and usable without curses
(`--once`).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from metis.core.ctf_contest import ContestBoard
from metis.core.ctf_swarm import status as swarm_status

STATE_ORDER = {"investigating": 0, "candidate": 1, "handoff": 2, "queued": 3, "blocked": 4, "abandoned": 5,
               "solved": 6}
STATE_MARK = {"solved": "OK ", "investigating": ">> ", "candidate": "?? ", "handoff": "HO ", "queued": ".. ",
              "blocked": "XX ", "abandoned": "-- "}


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}" if seconds >= 3600 \
        else f"{seconds // 60}:{seconds % 60:02d}"


def snapshot(database: Path, contest_id: str) -> dict[str, Any]:
    board = ContestBoard(database).board(contest_id)
    state = swarm_status(database, contest_id)
    activity_path = database.parent / "swarm" / contest_id / "activity.json"
    try:
        activity = json.loads(activity_path.read_text()) if activity_path.exists() else {}
    except ValueError:
        activity = {}
    return {"board": board, "status": state, "activity": activity}


def render(data: dict[str, Any], *, width: int = 120, now: float | None = None) -> list[tuple[str, str]]:
    """Return (text, style) lines; style is one of title, ok, active, warn, bad, dim, normal."""
    now = now or time.time()
    board, state, activity = data["board"], data["status"], data["activity"]
    counts = state["counts"]
    total = len(board["challenges"])
    lines: list[tuple[str, str]] = []

    def add(text: str, style: str = "normal") -> None:
        lines.append((text[:width], style))

    stop = "  [STOP requested]" if state["stop_requested"] else ""
    add(f"METIS swarm  {board['name']}  ({board['contest_id'][:8]})  {time.strftime('%H:%M:%S')}{stop}", "title")
    add(f"score {board['score']:g}   solved {counts['solved']}/{total}   working {counts['investigating']}   "
        f"queued {counts['queued']}   candidate {board['counts'].get('candidate', 0)}   "
        f"handoff {counts['handoff']}   blocked {counts['blocked']}", "title")
    done = counts["solved"] / total if total else 0
    bar = int(done * min(60, width - 10))
    add("[" + "#" * bar + "." * (min(60, width - 10) - bar) + f"] {done:.0%}", "ok")
    add("")
    add("WORKERS", "title")
    leases = {item["worker"]: item for item in state["active"]}
    workers = sorted(set(activity) | set(leases), key=lambda name: (len(name), name))
    if not workers:
        add("  (no worker activity yet)", "dim")
    for name in workers:
        info = activity.get(name, {})
        lease = leases.get(name)
        if lease:
            elapsed = _clock(now - info.get("started", now)) if info.get("challenge") == lease["challenge_id"] else "-"
            head = f"  {name:<4} {lease['challenge_id'][:24]:<24} {elapsed:>7}  "
            add(head + str(info.get("last", ""))[: max(10, width - len(head))], "active")
        else:
            age = _clock(now - info.get("time", now))
            add(f"  {name:<4} idle ({age} ago)  {str(info.get('last', ''))[:width - 30]}", "dim")
    add("")
    add("CHALLENGES", "title")
    for item in sorted(board["challenges"], key=lambda c: (STATE_ORDER.get(c["state"], 9), -c["points"])):
        mark = STATE_MARK.get(item["state"], "   ")
        worker = item.get("worker") or ""
        note = item.get("notes") or ""
        text = (f"  {mark}{item['challenge_id'][:26]:<26} {item['category'][:10]:<10} {item['points']:>6g}  "
                f"{item['state']:<13} {worker:<4} {note}")
        style = {"solved": "ok", "investigating": "active", "candidate": "warn", "handoff": "warn", "blocked": "bad",
                 "abandoned": "bad"}.get(item["state"], "normal")
        add(text, style)
    add("")
    add("RECENT EVENTS", "title")
    for event in state["recent_events"][-8:]:
        text = f"  {event.get('time', '')[-8:]} {event.get('worker', ''):<4} {event.get('event', '')} " \
               f"{event.get('challenge', '')} {event.get('state', '')}"
        style = "ok" if event.get("state") == "solved" else "warn" if event.get("event") == "timeout" else "dim"
        add(text, style)
    add("")
    if counts["handoff"]:
        add(f"{counts['handoff']} challenge(s) wait for you: metis swarm handoff {board['contest_id']} --prompt", "warn")
    add("q quit   s stop swarm (finish current challenges)   r refresh", "dim")
    return lines


def watch(database: Path, contest_id: str, *, interval: float = 2.0) -> None:  # pragma: no cover - interactive
    import curses

    def loop(screen: Any) -> None:
        curses.curs_set(0)
        screen.timeout(int(interval * 1000))
        styles = {"normal": 0}
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            for index, (name, colour) in enumerate((("ok", curses.COLOR_GREEN), ("active", curses.COLOR_CYAN),
                                                    ("warn", curses.COLOR_YELLOW), ("bad", curses.COLOR_RED),
                                                    ("title", curses.COLOR_WHITE), ("dim", curses.COLOR_BLUE)),
                                                   start=1):
                curses.init_pair(index, colour, -1)
                styles[name] = curses.color_pair(index) | (curses.A_BOLD if name == "title" else 0)
        while True:
            height, width = screen.getmaxyx()
            screen.erase()
            try:
                lines = render(snapshot(database, contest_id), width=width - 1)
            except Exception as exc:  # noqa: BLE001 -- keep the dashboard alive while state changes
                lines = [(f"waiting for state: {type(exc).__name__}: {exc}", "warn")]
            for row, (text, style) in enumerate(lines[:height - 1]):
                screen.addnstr(row, 0, text, width - 1, styles.get(style, 0))
            screen.refresh()
            key = screen.getch()
            if key in (ord("q"), ord("Q")):
                return
            if key in (ord("s"), ord("S")):
                stop = database.parent / "swarm" / contest_id / "STOP"
                stop.parent.mkdir(parents=True, exist_ok=True)
                stop.touch()

    curses.wrapper(loop)
