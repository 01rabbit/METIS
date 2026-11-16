"""`./play`: pick a contest, then work it in tmux with Claude Code and a live dashboard.

Menu (plain terminal input) -> tmux session ``metis-<contest id[:8]>`` with windows

  claude     interactive Claude Code, started with a prompt that knows the contest,
               its rules and what is waiting (refresh, handoff, queue)
  dashboard  `metis swarm watch`
  swarm/...  only when workers are requested (also addable later with
               `metis swarm run CONTEST --workers N --tmux` from any window)

Choosing a contest whose session is still running just re-attaches to it.
"""
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from metis.core.ctf_contest import ContestBoard
from metis.core.ctf_contest_ops import contest_info_report
from metis.core.ctf_platforms import PLATFORMS
from metis.core.ctf_swarm import dashboard_window, session_name, swarm_windows, tmux_windows

PROMPT_HEAD = """METIS の大会セッションを始めます。あなたは Daybreak（CLAUDE.md と .claude/skills/metis/SKILL.md に従う）です。
日本語で、短く報告しながら進めてください。

大会: {name}
contest_id: {contest_id}
サイト: {platform}  {url}
問題数 {total}、解決 {solved}、得点 {score:g}、状態別 {counts}
最終更新確認: {last_refresh}

この大会のルール（毎回守ること。違っていたらユーザーに確認して `metis contest configure` で直す）:
{rules}
"""

PROMPT_NEW = """
これは新しく登録した大会です。最初に次を行ってください。
1. `.venv/bin/metis doctor` で準備状態を確認する。
2. 大会ページを読み、ルール（提出方法、インスタンス数の制限、WriteUP の公開時期、開始・終了日時、
   自動アクセスに関する規約）を確認する。読めない項目はユーザーに一度だけまとめて質問する。
   結果を `printf '%s' '{{"rules": {{...}}}}' | .venv/bin/metis contest configure {contest_id}` で記録する。
   CTFd / rCTF と分かったら `"catalog": "ctfd"` または `"rctf"` と `"adapter"` も記録する。
3. 問題一覧を取り込む（下の「新着の取り込み」）。
4. 取り込んだら、並列ワーカーで解かせるか、ここで一緒に解くかをユーザーに聞く。
"""

PROMPT_CONTINUE = """
既存の大会の続きです。最初に次を行ってください。
1. 新着の取り込み（下記）で、ボードに無い問題だけを追加する。
2. `.venv/bin/metis contest info {contest_id}` で状況を3〜5行で報告する。
3. 引き継ぎ待ち（handoff）があれば `.venv/bin/metis swarm handoff {contest_id} --prompt` の内容に従って1問ずつ片付ける。
4. 未着手（queued）が残っていれば、並列ワーカーで解かせるか、ここで一緒に解くかをユーザーに聞く。
"""

REFRESH_API = """
新着の取り込み: `.venv/bin/metis contest refresh {contest_id}` を実行する（サイトの API から一覧を読む）。
"""

REFRESH_AGENT = """
新着の取り込み: 一覧ページ {url} を読む（{hint}）。
ボードと比べて足りない問題を JSON 配列で `.metis-state/work/{contest_id}-listing.json` に Write し、
`.venv/bin/metis contest refresh {contest_id} --file .metis-state/work/{contest_id}-listing.json` を実行する。
形式: {shape}
既存の問題は状態を変えずに残るので、一覧全体を渡してよい。サイトへのアクセスは一覧の確認1回程度にとどめる。
"""

PROMPT_TAIL = """
並列ワーカーの起動はあなた（Claude Code のサンドボックス内）からは行わない。ユーザーに、tmux で新しいウィンドウを
開いて（Ctrl-b のあと c）`.venv/bin/metis swarm run {contest_id} --workers 台数 --tmux` を実行するよう案内する。
ダッシュボードは tmux の dashboard ウィンドウにある（Ctrl-b のあと w で一覧から選ぶ）。
"""


def build_prompt(database: Path, contest_id: str, *, new: bool) -> str:
    from metis.core.ctf_contest_ops import LISTING_SHAPE

    info = contest_info_report(database, contest_id)
    meta = ContestBoard(database).meta(contest_id)
    counts = ", ".join(f"{key} {value}" for key, value in sorted(info["counts"].items())) or "なし"
    text = PROMPT_HEAD.format(name=info["name"], contest_id=contest_id, platform=info["platform"],
                              url=info["url"] or "（未登録）", total=info["total"],
                              solved=info["counts"].get("solved", 0), score=info["score"], counts=counts,
                              last_refresh=info["last_refresh"] or "未実施",
                              rules="\n".join("- " + line for line in info["rules_text"]))
    if not info["configured"]:
        text += ("（この大会のサイト情報とルールはまだ保存されていない。上はサイト種別からの推定なので、確認して\n"
                 f" `printf '%s' '{{\"url\": \"...\", \"rules\": {{...}}}}' | .venv/bin/metis contest configure {contest_id}`"
                 " で保存する）\n")
    text += (PROMPT_NEW if new else PROMPT_CONTINUE).format(contest_id=contest_id)
    if meta["catalog"] in {"ctfd", "rctf"}:
        text += REFRESH_API.format(contest_id=contest_id)
    else:
        hint = PLATFORMS.get(meta["platform"], {}).get(
            "list_hint", "CTFd / rCTF なら `metis web catalog URL --adapter ctfd|rctf` が使える。だめならブラウザで開く")
        text += REFRESH_AGENT.format(url=info["url"] or "（URL をユーザーに確認）", hint=hint,
                                     contest_id=contest_id, shape=LISTING_SHAPE)
    return text + PROMPT_TAIL.format(contest_id=contest_id)


def plan(database: Path, contest_id: str, *, root: Path, prompt: str, workers: int, chrome: bool,
         claude: str = "claude", worker_args: list[str] | None = None) -> list[list[str]]:
    """tmux commands for a play session (pure; tested without tmux)."""
    session = session_name(contest_id)
    agent = [claude, *(["--chrome"] if chrome else []), prompt]
    shell = os.environ.get("SHELL") or "/bin/sh"
    # Keep the window after Claude exits so the operator can restart it (`claude --continue`).
    lead = shlex.join(agent) + "; echo; echo '[Claude Code を終了しました。再開: claude --continue]'; exec " \
        + shlex.quote(shell)
    commands = [["tmux", "new-session", "-d", "-s", session, "-n", "claude", "-c", str(root), lead],
                dashboard_window(database, contest_id, root)]
    if workers:
        run_args = ["--workers", str(workers), *(["--chrome"] if chrome else []), *(worker_args or [])]
        commands += swarm_windows(database, contest_id, run_args, workers, root, new_session=False)
    commands.append(["tmux", "select-window", "-t", f"{session}:claude"])
    return commands


# -- interactive menu ------------------------------------------------------------------
def _ask(text: str, default: str = "") -> str:
    try:
        answer = input(text).strip()
    except EOFError:
        raise SystemExit(0) from None
    return answer or default


def _menu(database: Path) -> tuple[str, bool] | None:
    board = ContestBoard(database)
    contests = board.contests()
    from metis.play_tui import banner_text, gather

    print(banner_text(gather(database, Path.cwd())))
    print("大会を選んでください\n")
    for number, item in enumerate(contests, 1):
        solved = item["counts"].get("solved", 0)
        waiting = item["counts"].get("handoff", 0)
        running = " [実行中]" if tmux_windows(session_name(item["contest_id"])) is not None else ""
        extra = f"  引き継ぎ待ち {waiting}" if waiting else ""
        print(f"  {number}) {item['name'][:30]:<30} {item['platform']:<10} "
              f"{solved}/{item['challenges']}  {item['score']:g}点{extra}{running}")
    print("  n) 新しい大会（URL を入力）")
    print("  q) 終了\n")
    choice = _ask("番号を入力: ").lower()
    if choice in {"q", ""}:
        return None
    if choice == "n":
        url = _ask("大会（問題一覧）の URL: ")
        if not url:
            return None
        name = _ask("大会名（空欄ならホスト名）: ") or None
        created = board.new(url, name)
        print(f"登録しました: {created['name']}（{created['contest_id']}）サイト種別: {created['platform']}")
        if created["platform"] == "unknown":
            print("未知のサイトです。Claude Code が最初に一覧の読み方とルールを確認します。")
        return created["contest_id"], True
    if choice.isdigit() and 1 <= int(choice) <= len(contests):
        return contests[int(choice) - 1]["contest_id"], False
    print("選択が正しくありません。")
    return None


def _attach(session: str) -> None:
    command = ["tmux", "switch-client", "-t", session] if os.environ.get("TMUX") else ["tmux", "attach", "-t", session]
    os.execvp("tmux", command)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="play", description=__doc__.splitlines()[0])
    parser.add_argument("contest_id", nargs="?", help="skip the menu and continue this contest")
    parser.add_argument("--new", metavar="URL", help="register a new contest from its URL and start")
    parser.add_argument("--name")
    parser.add_argument("--workers", type=int, help="start N swarm workers too (default: ask)")
    parser.add_argument("--no-chrome", action="store_true", help="start Claude Code without Claude in Chrome")
    parser.add_argument("--database", type=Path, default=Path(".metis-state/metis.sqlite"))
    parser.add_argument("--print-prompt", action="store_true", help="print the Claude prompt and exit")
    parser.add_argument("--plain", action="store_true", help="numbered text menu instead of the start screen")
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    for tool, hint in (("tmux", "brew install tmux"), ("claude", "Claude Code をインストールしてください")):
        if shutil.which(tool) is None and not args.print_prompt:
            print(f"{tool} が見つかりません（{hint}）。", file=sys.stderr)
            return 1
    board = ContestBoard(args.database)
    if args.new:
        created = board.new(args.new, args.name)
        selected: tuple[str, bool] | None = (created["contest_id"], True)
    elif args.contest_id:
        board.meta(args.contest_id)
        selected = (args.contest_id, False)
    elif sys.stdin.isatty() and sys.stdout.isatty() and not args.plain:
        from metis.play_tui import run as start_screen

        choice = start_screen(args.database, root, workers=args.workers or 0)
        if choice is None:
            return 0
        selected = (choice["contest_id"], choice["new"])
        args.workers = choice["workers"]
    else:
        selected = _menu(args.database)
    if selected is None:
        return 0
    contest_id, new = selected
    prompt = build_prompt(args.database, contest_id, new=new)
    if args.print_prompt:
        print(prompt)
        return 0
    session = session_name(contest_id)
    if tmux_windows(session) is not None:
        print(f"実行中のセッション {session} に戻ります。")
        _attach(session)
    workers = args.workers
    if workers is None:
        answer = _ask("並列ワーカーも起動しますか？ 台数を入力（0 = Claude と一緒に進める）[0]: ", "0")
        workers = int(answer) if answer.isdigit() else 0
    if not 0 <= workers <= 16:
        print("ワーカーは 0〜16 台です。", file=sys.stderr)
        return 1
    rules: dict[str, Any] = board.meta(contest_id)["rules"]
    if workers > 1 and rules.get("instance_limit") == 1:
        print("注意: この大会はインスタンス同時起動が1つです。インスタンスが要る問題はワーカーが handoff にします。")
    for command in plan(args.database, contest_id, root=root, prompt=prompt, workers=workers,
                        chrome=not args.no_chrome):
        subprocess.run(command, check=True)
    print(f"tmux セッション {session}: claude, dashboard" + (", swarm, workers" if workers else ""))
    print("切り替え: Ctrl-b のあと n（次）/ w（一覧）  一時的に離れる: Ctrl-b のあと d  戻る: ./play で同じ大会を選ぶ")
    _attach(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
