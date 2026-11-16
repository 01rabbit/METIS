"""Validate manifests, inspect evidence and run bounded authorized local fixtures."""
from __future__ import annotations

import argparse
import getpass
import http.client
import importlib.metadata
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from metis import __version__
from metis.core.artifacts import read_artifact
from metis.core.codex_session import CodexSession
from metis.core.contracts import ChallengeManifest, RunBudget, RunEvent, RunStatus
from metis.core.ctf_artifacts import ARTIFACT_TOOLS, MAX_ARTIFACT, MAX_FILE
from metis.core.ctf_browser import available as browser_available
from metis.core.ctf_contest import ContestBoard
from metis.core.ctf_contest_ops import contest_info_report
from metis.core.ctf_contest_ops import contest_refresh as refresh_contest
from metis.core.ctf_dashboard import render as render_dashboard
from metis.core.ctf_dashboard import snapshot as dashboard_snapshot
from metis.core.ctf_dashboard import watch as watch_dashboard
from metis.core.ctf_knowledge import KnowledgeBase, TechniqueCard
from metis.core.ctf_orchestration import AgentLedger
from metis.core.ctf_practice import practice
from metis.core.ctf_proxy import describe_environment
from metis.core.ctf_remote import Exchange, RemoteWorkflow
from metis.core.ctf_sandbox import (
    EMULATE_CHOICES,
    MODES,
    Sandbox,
    SandboxRequest,
    build_image,
    configure,
)
from metis.core.ctf_sandbox import status as sandbox_status
from metis.core.ctf_swarm import Swarm, launch_tmux
from metis.core.ctf_swarm import handoff as handoff_report
from metis.core.ctf_swarm import status as swarm_status_report
from metis.core.ctf_tools import DATA_TOOLS
from metis.core.ctf_web import WebRequest, WebWorkflow
from metis.core.ctf_writeup import WriteupBook, WriteupInput
from metis.core.fixtures import generate_fixtures
from metis.core.models import FixtureProvider, ModelProvider
from metis.core.openai_provider import OpenAIProvider
from metis.core.runner import Runner
from metis.core.runtime import FixtureRuntime, ToolRequest
from metis.core.store import RunStore
from metis.core.verification import FixtureOracle


def read_candidate(path: Path | None) -> str:
    """Exact candidate from a file (agent-friendly: no shell pipe) or stdin.

    One trailing LF or CRLF is removed so editor- or echo-written input does not
    change the candidate; every other byte is kept.
    """
    raw = path.read_bytes()[:65_537] if path is not None else sys.stdin.buffer.read(65_537)
    if raw.endswith(b"\r\n"):
        raw = raw[:-2]
    elif raw.endswith(b"\n"):
        raw = raw[:-1]
    return raw.decode()


def main() -> int:
    output: dict[str, Any]
    parser = argparse.ArgumentParser(prog="metis")
    parser.add_argument("--version", action="version", version=f"METIS {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check native CTF tools without API keys or Docker")
    agent_plan = sub.add_parser("plan", help="create a provider-neutral bounded agent wave")
    agent_plan.add_argument("run_id")
    agent_plan.add_argument("--database", type=Path, default=Path(".metis-state/metis.sqlite"))
    contest = sub.add_parser("contest", help="prioritize and track a large CTF")
    contest.add_argument("--database", type=Path, default=Path(".metis-state/metis.sqlite"))
    contest_commands = contest.add_subparsers(dest="contest_command", required=True)
    contest_commands.add_parser("create", help="read contest configuration JSON from stdin")
    contest_add = contest_commands.add_parser("add", help="read a challenge array from stdin")
    contest_add.add_argument("contest_id")
    contest_update = contest_commands.add_parser("update", help="read challenge changes from stdin")
    contest_update.add_argument("contest_id")
    contest_update.add_argument("challenge_id")
    contest_commands.add_parser("list", help="list contests with their IDs and progress")
    contest_new = contest_commands.add_parser("new", help="create a contest from its URL with platform defaults")
    contest_new.add_argument("url")
    contest_new.add_argument("--name")
    contest_new.add_argument("--max-parallel", type=int, default=4)
    contest_configure = contest_commands.add_parser(
        "configure", help="set platform/url/adapter/catalog and merge rules from stdin JSON")
    contest_configure.add_argument("contest_id")
    contest_info = contest_commands.add_parser("info", help="platform, rules and progress summary")
    contest_info.add_argument("contest_id")
    contest_refresh = contest_commands.add_parser(
        "refresh", help="add new challenges from the platform (API) or from --file (list read by the agent)")
    contest_refresh.add_argument("contest_id")
    contest_refresh.add_argument("--file", type=Path, help="JSON array of challenges read from the list page")
    contest_refresh.add_argument("--token-env")
    contest_refresh.add_argument("--cookie-env")
    contest_claim = contest_commands.add_parser("claim", help="lease the best queued challenge to a worker")
    contest_claim.add_argument("contest_id")
    contest_claim.add_argument("--worker", required=True)
    contest_claim.add_argument("--lease", type=int, default=2400, help="lease seconds (renew with heartbeat)")
    contest_heartbeat = contest_commands.add_parser("heartbeat", help="extend a worker's lease")
    contest_heartbeat.add_argument("contest_id")
    contest_heartbeat.add_argument("challenge_id")
    contest_heartbeat.add_argument("--worker", required=True)
    contest_heartbeat.add_argument("--lease", type=int, default=2400)
    contest_release = contest_commands.add_parser("release", help="end a lease with the next lifecycle state")
    contest_release.add_argument("contest_id")
    contest_release.add_argument("challenge_id")
    contest_release.add_argument("--worker", required=True)
    contest_release.add_argument("--state", required=True,
                                 choices=("queued", "handoff", "blocked", "abandoned", "candidate", "solved"))
    contest_release.add_argument("--note")
    contest_sync = contest_commands.add_parser("sync", help="link existing runs from a platform; mark solved ones")
    contest_sync.add_argument("contest_id")
    contest_sync.add_argument("--origin", required=True, help="platform URL, e.g. https://ksnctf.sweetduet.info")
    contest_dispatch = contest_commands.add_parser("dispatch", help="allocate available AI work slots")
    contest_dispatch.add_argument("contest_id")
    contest_board = contest_commands.add_parser("board", help="show score, lifecycle and queue state")
    contest_board.add_argument("contest_id")
    agent = sub.add_parser("agent", help="record and synthesize bounded subagent evidence")
    agent.add_argument("--database", type=Path, default=Path(".metis-state/metis.sqlite"))
    agent_commands = agent.add_subparsers(dest="agent_command", required=True)
    report = agent_commands.add_parser("report", help="read one compact evidence report from stdin")
    report.add_argument("run_id")
    report.add_argument("wave_id")
    report.add_argument("assignment_id")
    synthesis = agent_commands.add_parser("synthesize", help="combine one completed agent wave")
    synthesis.add_argument("run_id")
    synthesis.add_argument("wave_id")
    web = sub.add_parser("web", help="generic scoped CTF problem intake and official submission")
    web.add_argument("--database", type=Path, default=Path(".metis-state/metis.sqlite"))
    web_commands = web.add_subparsers(dest="web_command", required=True)
    catalog = web_commands.add_parser("catalog", help="retrieve a bounded CTFd or rCTF challenge list")
    catalog.add_argument("url")
    catalog.add_argument("--adapter", choices=("ctfd", "rctf"), default="ctfd")
    catalog.add_argument("--token-env")
    catalog.add_argument("--cookie-env")
    web_open = web_commands.add_parser("open", help="retrieve problem text and same-origin distribution files")
    web_open.add_argument("url")
    web_open.add_argument("--adapter", choices=("auto", "html", "ctfd", "rctf", "ksnctf"), default="auto",
                          help="auto recognizes supported official problem URLs; otherwise uses HTML")
    web_open.add_argument("--challenge-id", help="CTFd numeric ID or rCTF challenge ID")
    web_open.add_argument("--render", action="store_true",
                          help="render JavaScript pages in scoped headless Chromium (browser extra)")
    web_open.add_argument("--allow-origin", action="append", default=[])
    web_open.add_argument("--token-env")
    web_open.add_argument("--cookie-env")
    web_open.add_argument("--no-download", action="store_true")
    auth = web_commands.add_parser("auth", help="privately store an existing CTF cookie or token via a masked terminal prompt")
    auth.add_argument("url")
    auth.add_argument("--kind", choices=("cookie", "token", "rctf-team-token"), required=True,
                      help="rctf-team-token logs in once and stores only the derived Bearer auth token")
    auth.add_argument("--scheme", choices=("Token", "Bearer"), default="Token")
    web_context = web_commands.add_parser("context")
    web_context.add_argument("run_id")
    web_grant = web_commands.add_parser("grant", help="add a user-authorized challenge origin to a run")
    web_grant.add_argument("run_id")
    web_grant.add_argument("url")
    web_request = web_commands.add_parser("request", help="send scoped HTTP request(s) to granted challenge origins")
    web_request.add_argument("run_id")
    web_request.add_argument("url", nargs="?")
    web_request.add_argument("--method", default="GET")
    web_request.add_argument("--header", action="append", default=[], help="'Name: value' (repeatable)")
    web_request_body = web_request.add_mutually_exclusive_group()
    web_request_body.add_argument("--data")
    web_request_body.add_argument("--data-hex")
    web_request_body.add_argument("--form", action="append", help="key=value form field (repeatable)")
    web_request_body.add_argument("--json", dest="json_body", help="JSON request body")
    web_request.add_argument("--follow", action="store_true", help="follow redirects within scope")
    web_request.add_argument("--extract", help="regular expression; matches are returned")
    web_request.add_argument("--preview", type=int, default=4096)
    web_request.add_argument("--batch", type=Path,
                             help='JSON list (or {"requests": [...]}) of up to 256 request objects')
    web_attest = web_commands.add_parser(
        "attest", help="record an official verdict seen in the platform's web UI (candidate on stdin)")
    web_attest.add_argument("run_id")
    web_attest.add_argument("--verdict", choices=("correct", "incorrect"), required=True)
    web_attest.add_argument("--evidence", required=True, help="what the platform UI showed, without the flag")
    web_attest.add_argument("--candidate-file", type=Path,
                            help="read the exact candidate from this file instead of stdin")
    web_submit = web_commands.add_parser("submit", help="submit exact candidate from stdin and inspect the official verdict")
    web_submit.add_argument("run_id")
    web_submit.add_argument("--candidate-file", type=Path,
                            help="read the exact candidate from this file instead of stdin")
    form = web_commands.add_parser("configure-form", help="configure a trusted generic POST form before any submission")
    form.add_argument("run_id")
    form.add_argument("--form-index", type=int, required=True)
    form.add_argument("--flag-field", required=True)
    form.add_argument("--selector", required=True)
    form.add_argument("--correct-text", required=True)
    form.add_argument("--incorrect-text", required=True)
    remote = sub.add_parser("remote", help="scoped TCP/TLS interaction with a granted challenge service")
    remote.add_argument("--database", type=Path, default=Path(".metis-state/metis.sqlite"))
    remote_commands = remote.add_subparsers(dest="remote_command", required=True)
    suggest = remote_commands.add_parser("suggest", help="list nc-style endpoints in the statement (not grants)")
    suggest.add_argument("run_id")
    grant = remote_commands.add_parser("grant", help="record a user-authorized host and port for this run")
    grant.add_argument("run_id")
    grant.add_argument("host")
    grant.add_argument("port", type=int)
    grant.add_argument("--tls", action="store_true")
    grant.add_argument("--replace", action="store_true",
                       help="revoke this run's other endpoints (new instance of the same challenge)")
    endpoints_parser = remote_commands.add_parser("list", help="granted endpoints of a run (active, latest)")
    endpoints_parser.add_argument("run_id")
    revoke = remote_commands.add_parser("revoke", help="revoke one granted endpoint")
    revoke.add_argument("run_id")
    revoke.add_argument("endpoint", help="index, host:port or latest")
    exchange = remote_commands.add_parser("exchange", help="run a bounded JSON send/receive script")
    exchange.add_argument("run_id")
    exchange.add_argument("index", help="index, host:port or latest (newest active grant)")
    exchange.add_argument("--script", type=Path, help='JSON {"steps":[...]}; stdin when omitted')
    connect = remote_commands.add_parser("connect", help="bridge this process's stdin/stdout to the service "
                                         "(nc-like; usable as an ssh ProxyCommand)")
    connect.add_argument("run_id")
    connect.add_argument("index", help="index, host:port or latest (newest active grant)")
    connect.add_argument("--timeout", type=float, default=3600)
    ssh = remote_commands.add_parser("ssh", help="run a command and/or download files over SSH on a granted endpoint")
    ssh.add_argument("run_id")
    ssh.add_argument("index", help="index, host:port or latest (newest active grant)")
    ssh.add_argument("--user", required=True)
    ssh.add_argument("--command", dest="ssh_command", help="remote command to execute")
    ssh.add_argument("--get", action="append", default=[], help="remote file to fetch as a run artifact")
    ssh_auth = ssh.add_mutually_exclusive_group()
    ssh_auth.add_argument("--password-stdin", action="store_true",
                          help="read the password from the first line of stdin")
    ssh_auth.add_argument("--password-env", help="environment variable holding the password")
    ssh_auth.add_argument("--key", type=Path, help="private key file")
    ssh.add_argument("--stdin-file", type=Path, help="bytes sent to the remote command's stdin")
    ssh.add_argument("--pty", action="store_true", help="allocate a pseudo-terminal")
    ssh.add_argument("--timeout", type=float, default=60)
    pipe = remote_commands.add_parser("pipe", help="bridge an agent-authored solver's stdio to the service")
    pipe.add_argument("run_id")
    pipe.add_argument("index", help="index, host:port or latest (newest active grant)")
    pipe.add_argument("--timeout", type=float, default=120)
    pipe.add_argument("solver", nargs=argparse.REMAINDER, help="-- COMMAND [ARGS...]")
    sandbox = sub.add_parser("sandbox", help="run challenge programs only inside an isolated container")
    sandbox.add_argument("--database", type=Path, default=Path(".metis-state/metis.sqlite"))
    sandbox_commands = sandbox.add_subparsers(dest="sandbox_command", required=True)
    sandbox_commands.add_parser("status", help="show engine and image readiness")
    build = sandbox_commands.add_parser("build", help="build the bundled image and record its immutable ID")
    build.add_argument("--engine", choices=("docker", "podman"), default="docker")
    build.add_argument("--platform", default="auto",
                       help="auto (host CPU, recommended), native, or linux/amd64|arm64|386|arm/v7")
    sandbox_configure = sandbox_commands.add_parser("configure", help="use an existing immutable image")
    sandbox_configure.add_argument("--engine", choices=("docker", "podman"), default="docker")
    sandbox_configure.add_argument("--image", required=True)
    sandbox_configure.add_argument("--platform")
    sandbox_run = sandbox_commands.add_parser("run", help="execute a declared artifact inside the sandbox")
    sandbox_run.add_argument("run_id")
    sandbox_run.add_argument("target", help="declared artifact name from context")
    sandbox_run.add_argument("--mode", choices=MODES, default="run")
    sandbox_run.add_argument("--arg", action="append", default=[], help="program argument (repeatable)")
    sandbox_run.add_argument("--with", dest="extra", action="append", default=[],
                             help="additional declared artifact copied beside the target (libc, ld, data)")
    sandbox_run.add_argument("--stdin-file", type=Path)
    sandbox_run.add_argument("--stdin-hex")
    sandbox_run.add_argument("--gdb", action="append", default=[], help="gdb batch command (repeatable)")
    sandbox_run.add_argument("--script", type=Path, help="agent-authored script for --mode script")
    sandbox_run.add_argument("--interpreter", choices=("python3", "sh", "bash"), default="python3")
    sandbox_run.add_argument("--timeout", type=int, default=20)
    sandbox_run.add_argument("--emulate", choices=EMULATE_CHOICES, default="auto",
                             help="auto runs foreign-architecture ELF targets through QEMU")
    swarm = sub.add_parser("swarm", help="run independent agent workers on a contest board in parallel")
    swarm.add_argument("--database", type=Path, default=Path(".metis-state/metis.sqlite"))
    swarm_commands = swarm.add_subparsers(dest="swarm_command", required=True)
    swarm_run = swarm_commands.add_parser("run", help="start N workers; each leases one challenge at a time")
    swarm_run.add_argument("contest_id")
    swarm_run.add_argument("--workers", type=int, default=8)
    swarm_run.add_argument("--agent", choices=("claude", "codex"), default="claude")
    swarm_run.add_argument("--minutes", type=int, default=40, help="time box per challenge session")
    swarm_run.add_argument("--max-sessions", type=int, default=2,
                           help="sessions per challenge before it is marked blocked")
    swarm_run.add_argument("--chrome", action="store_true", help="give Claude Code workers the Chrome browser")
    swarm_run.add_argument("--model")
    swarm_run.add_argument("--once", action="store_true", help="each worker handles one challenge, then stops")
    swarm_run.add_argument("--tmux", action="store_true",
                           help="run inside a tmux session with a live dashboard and one log pane per worker")
    swarm_run.add_argument("--agent-arg", dest="agent_args", action="append", default=[],
                           help="extra argument for the agent CLI, e.g. --agent-arg=--verbose (repeatable)")
    swarm_watch = swarm_commands.add_parser("watch", help="live terminal dashboard (q quit, s stop)")
    swarm_watch.add_argument("contest_id")
    swarm_watch.add_argument("--interval", type=float, default=2.0)
    swarm_watch.add_argument("--once", action="store_true", help="print one plain-text snapshot and exit")
    swarm_status = swarm_commands.add_parser("status", help="leases, counts and recent events")
    swarm_status.add_argument("contest_id")
    swarm_handoff = swarm_commands.add_parser(
        "handoff", help="challenges waiting for your browser step, with a ready-to-paste Claude Code prompt")
    swarm_handoff.add_argument("contest_id")
    swarm_handoff.add_argument("--prompt", action="store_true", help="print only the prompt text")
    swarm_stop = swarm_commands.add_parser("stop", help="workers finish their current challenge, then exit")
    swarm_stop.add_argument("contest_id")
    writeup = sub.add_parser("writeup", help="per-CTF Markdown write-ups and the technique index")
    writeup.add_argument("--database", type=Path, default=Path(".metis-state/metis.sqlite"))
    writeup.add_argument("--root", type=Path, default=Path("writeups"))
    writeup_commands = writeup.add_subparsers(dest="writeup_command", required=True)
    writeup_save = writeup_commands.add_parser("save", help="write one problem's write-up from JSON (stdin or --file)")
    writeup_save.add_argument("contest_id")
    writeup_save.add_argument("challenge_id")
    writeup_save.add_argument("--file", type=Path)
    writeup_index = writeup_commands.add_parser("index", help="regenerate a CTF's README table")
    writeup_index.add_argument("contest_id")
    writeup_commands.add_parser("knowledge", help="regenerate KNOWLEDGE.md from technique cards")
    writeup_missing = writeup_commands.add_parser("missing", help="list solved problems without a write-up")
    writeup_missing.add_argument("contest_id")
    memory = sub.add_parser("memory", help="MUNIN: reusable techniques and evidence-based revisions")
    memory.add_argument("--database", type=Path, default=Path(".metis-state/metis.sqlite"))
    memory_commands = memory.add_subparsers(dest="memory_command", required=True)
    search = memory_commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--category", choices=("web", "crypto", "pwn", "rev", "forensics", "misc"))
    search.add_argument("--limit", type=int, default=5)
    memory_commands.add_parser("learn", help="read an abstract technique card JSON from stdin")
    reason = memory_commands.add_parser("reason", help="record a concise revised hypothesis, evidence and next step")
    reason.add_argument("run_id")
    reason.add_argument("--summary", required=True)
    reason.add_argument("--evidence", required=True)
    reason.add_argument("--next-step", required=True)
    reason.add_argument("--status", choices=("proposed", "revised", "rejected", "supported"), default="revised")
    hypotheses_parser = memory_commands.add_parser("hypotheses")
    hypotheses_parser.add_argument("run_id")
    validate = sub.add_parser("validate", help="validate an authorized challenge manifest")
    validate.add_argument("manifest", type=Path)
    prepare = sub.add_parser("prepare", help="validate and record a run without executing tools")
    prepare.add_argument("manifest", type=Path)
    prepare.add_argument("--database", type=Path, required=True)
    inspect = sub.add_parser("inspect", help="read validated run history without modifying it")
    inspect.add_argument("run_id")
    inspect.add_argument("--database", type=Path, required=True)
    generate = sub.add_parser("generate-fixtures", help="generate two synthetic local puzzles")
    generate.add_argument("directory", type=Path)
    generate.add_argument("--oracle", type=Path, required=True)
    run = sub.add_parser("run", help="run an authorized local decoding fixture")
    run.add_argument("manifest", type=Path)
    run.add_argument("--database", type=Path, required=True)
    run.add_argument("--oracle", type=Path, required=True)
    run.add_argument("--image", required=True, help="trusted digest-pinned Python Docker image")
    run.add_argument("--provider", choices=("fixture", "openai"), default="fixture")
    run.add_argument("--model", default="gpt-4.1-mini")
    run.add_argument("--max-call-cost-usd", type=float)
    run.add_argument("--max-actions", type=int, default=40)
    run.add_argument("--wall-time-seconds", type=int, default=1200)
    run.add_argument("--per-tool-seconds", type=int, default=30)
    run.add_argument("--max-model-tokens", type=int, default=100_000)
    run.add_argument("--max-cost-usd", type=float, default=10)
    run.add_argument("--stop-file", type=Path,
                     help="controller-owned cancellation marker checked between calls")
    codex = sub.add_parser("codex", help="Codex-native sessions: no API key or Docker")
    codex.add_argument("--database", type=Path, default=Path(".metis-state/metis.sqlite"))
    commands = codex.add_subparsers(dest="codex_command", required=True)
    commands.add_parser("demo", help="create two local puzzles without plaintext answer storage")
    commands.add_parser("practice", help="generate six offline category/toolchain exercises")
    board = commands.add_parser("board", help="show challenge states without dumping observations")
    board.add_argument("--limit", type=int, default=30)
    start = commands.add_parser("start", help="start an inline authorized local puzzle")
    start.add_argument("manifest", type=Path)
    start.add_argument("--expected-sha256")
    start.add_argument("--max-actions", type=int, default=40)
    start.add_argument("--wall-seconds", type=int, default=1200)
    start.add_argument("--artifact-root", type=Path)
    commands.add_parser("tools", help="list inline and read-only artifact tools")
    plan = commands.add_parser("plan", help="create a bounded Daybreak subagent wave")
    plan.add_argument("run_id")
    intake = commands.add_parser("intake", help="start from supplied text/files without writing a manifest")
    intake.add_argument("--title", default="User-provided CTF challenge")
    intake.add_argument("--description", default="Analyze the explicitly supplied local challenge files.")
    intake.add_argument("--artifact", type=Path, action="append", default=[])
    intake.add_argument("--category", choices=("pwn", "rev", "web", "crypto", "forensics", "misc"),
                        action="append", default=[])
    intake.add_argument("--expected-sha256")
    intake.add_argument("--max-actions", type=int, default=80)
    intake.add_argument("--wall-seconds", type=int, default=3600)
    artifact = commands.add_parser("artifact", help="inspect one declared artifact without executing it")
    artifact.add_argument("run_id")
    artifact.add_argument("name")
    artifact.add_argument("analysis", choices=sorted(ARTIFACT_TOOLS))
    artifact.add_argument("--options", default="{}", help="bounded JSON analysis options")
    derive = commands.add_parser("derive", help="materialize a bounded archive member as a scoped artifact")
    derive.add_argument("run_id")
    derive.add_argument("name")
    derive.add_argument("analysis", choices=("zip_read", "tar_read", "gzip", "zlib", "bzip2", "xz",
                                            "base64_decode", "base32_decode", "hex_decode"))
    derive.add_argument("--options", default="{}")
    add_file = commands.add_parser("add-file", help="add a file you downloaded yourself (e.g. in the browser) to a run")
    add_file.add_argument("run_id")
    add_file.add_argument("path", type=Path)
    extend = commands.add_parser("extend", help="operator budget extension; resumes a budget-exhausted run")
    extend.add_argument("run_id")
    extend.add_argument("--actions", type=int, default=0)
    extend.add_argument("--seconds", type=int, default=0)
    for command in ("context", "act", "submit", "cancel", "recover"):
        action = commands.add_parser(command)
        action.add_argument("run_id")
        if command == "act":
            action.add_argument("tool", choices=sorted(DATA_TOOLS))
            action.add_argument("--data", help="omit to read exact UTF-8 input from stdin")
    args = parser.parse_args()

    if args.command == "swarm":
        try:
            if args.swarm_command == "run" and args.tmux:
                ContestBoard(args.database)._contest(args.contest_id)
                forwarded = ["--workers", str(args.workers), "--agent", args.agent, "--minutes", str(args.minutes),
                             "--max-sessions", str(args.max_sessions),
                             *(["--chrome"] if args.chrome else []), *(["--once"] if args.once else []),
                             *(["--model", args.model] if args.model else []),
                             *[f"--agent-arg={value}" for value in args.agent_args]]
                launched = launch_tmux(args.database, args.contest_id, forwarded, args.workers)
                print(json.dumps({k: v for k, v in launched.items() if k != "attach_command"}, ensure_ascii=False),
                      flush=True)
                os.execvp("tmux", launched["attach_command"])
            if args.swarm_command == "watch":
                if args.once:
                    for text, _ in render_dashboard(dashboard_snapshot(args.database, args.contest_id),
                                                    width=shutil.get_terminal_size((120, 40)).columns):
                        print(text)
                else:
                    watch_dashboard(args.database, args.contest_id, interval=args.interval)
                return 0
            if args.swarm_command == "run":
                extra = args.agent_args
                swarm_runner = Swarm(args.database, args.contest_id, workers=args.workers, agent=args.agent,
                               minutes=args.minutes, max_sessions=args.max_sessions, chrome=args.chrome,
                               model=args.model, agent_args=extra)
                print(json.dumps({"started": True, "workers": args.workers, "logs": str(swarm_runner.logs),
                                  "stop": f"metis swarm stop {args.contest_id}"}, ensure_ascii=False), flush=True)
                output = swarm_runner.run(once=args.once)
            elif args.swarm_command == "status":
                output = swarm_status_report(args.database, args.contest_id)
            elif args.swarm_command == "handoff":
                output = handoff_report(args.database, args.contest_id)
                if args.prompt:
                    print(output["prompt"] or "引き継ぎ待ちの問題はありません。")
                    return 0
            else:
                ContestBoard(args.database)._contest(args.contest_id)
                stop = args.database.parent / "swarm" / args.contest_id / "STOP"
                stop.parent.mkdir(parents=True, exist_ok=True)
                stop.touch()
                output = {"stop_requested": True, "file": str(stop)}
            print(json.dumps(output, ensure_ascii=False))
            return 0
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            swarm_reason = (str(exc).splitlines() or [type(exc).__name__])[0][:400]
            parser.exit(2, "Swarm command rejected: " + swarm_reason + "\n")
    if args.command == "writeup":
        try:
            book = WriteupBook(args.database, args.root)
            if args.writeup_command == "save":
                raw = (args.file.read_bytes() if args.file is not None else sys.stdin.buffer.read(262_145))
                if len(raw) > 262_144:
                    raise ValueError("write-up input exceeds 256 KiB")
                output = book.save(args.contest_id, args.challenge_id, WriteupInput.model_validate_json(raw))
            elif args.writeup_command == "index":
                output = book.index(args.contest_id)
            elif args.writeup_command == "knowledge":
                output = book.export_knowledge()
            else:
                output = book.missing(args.contest_id)
            print(json.dumps(output, ensure_ascii=False))
            return 0
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            writeup_reason = (str(exc).splitlines() or [type(exc).__name__])[0][:400]
            parser.exit(2, "Write-up command rejected: " + writeup_reason + "\n")
    if args.command == "memory":
        try:
            knowledge = KnowledgeBase(args.database)
            if args.memory_command == "search":
                output = {"cards": knowledge.search(args.query, category=args.category, limit=args.limit)}
            elif args.memory_command == "learn":
                raw = sys.stdin.buffer.read(16_385)
                if len(raw) > 16_384:
                    raise ValueError("technique card exceeds limit")
                output = knowledge.remember(TechniqueCard.model_validate_json(raw))
            elif args.memory_command == "hypotheses":
                output = {"hypotheses": knowledge.hypotheses(args.run_id)}
            else:
                output = knowledge.reason(args.run_id, summary=args.summary, evidence=args.evidence,
                                           next_step=args.next_step, status=args.status)
            print(json.dumps(output))
            return 0
        except (OSError, ValueError, TypeError, sqlite3.Error):
            parser.exit(2, "Knowledge command rejected: use abstract, evidence-backed methods without flags or credentials\n")
    if args.command == "plan":
        try:
            print(json.dumps(AgentLedger(args.database).create_wave(args.run_id)))
            return 0
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error):
            parser.exit(2, "Agent plan rejected: check the run ID and local session state\n")
    if args.command == "contest":
        try:
            contest_state = ContestBoard(args.database)
            payload: Any = None
            if args.contest_command in {"create", "add", "update", "configure"}:
                raw = sys.stdin.buffer.read(262_145)
                if len(raw) > 262_144:
                    raise ValueError("contest input exceeds limit")
                payload = json.loads(raw)
            if args.contest_command == "create":
                if not isinstance(payload, dict):
                    raise ValueError("contest configuration must be an object")
                output = contest_state.create(payload)
            elif args.contest_command == "add":
                items = payload.get("challenges") if isinstance(payload, dict) else payload
                if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                    raise ValueError("challenge input must be an array of objects")
                output = contest_state.add(args.contest_id, items)
            elif args.contest_command == "update":
                if not isinstance(payload, dict):
                    raise ValueError("challenge update must be an object")
                output = contest_state.update(args.contest_id, args.challenge_id, payload)
            elif args.contest_command == "list":
                output = {"contests": contest_state.contests()}
            elif args.contest_command == "new":
                output = contest_state.new(args.url, args.name, max_parallel=args.max_parallel)
            elif args.contest_command == "configure":
                if not isinstance(payload, dict):
                    raise ValueError("configuration must be an object")
                output = contest_state.configure(args.contest_id, payload)
            elif args.contest_command == "info":
                output = contest_info_report(args.database, args.contest_id)
            elif args.contest_command == "refresh":
                output = refresh_contest(args.database, args.contest_id, listing_file=args.file,
                                         token_env=args.token_env, cookie_env=args.cookie_env)
            elif args.contest_command == "claim":
                output = contest_state.claim(args.contest_id, args.worker, lease_seconds=args.lease)
            elif args.contest_command == "heartbeat":
                output = contest_state.heartbeat(args.contest_id, args.challenge_id, args.worker,
                                                 lease_seconds=args.lease)
            elif args.contest_command == "release":
                output = contest_state.release(args.contest_id, args.challenge_id, args.worker,
                                               state=args.state, note=args.note)
            elif args.contest_command == "sync":
                output = contest_state.sync(args.contest_id, args.origin)
            elif args.contest_command == "dispatch":
                output = contest_state.dispatch(args.contest_id)
            else:
                output = contest_state.board(args.contest_id)
            print(json.dumps(output))
            return 0
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error) as exc:
            contest_reason = (str(exc).splitlines() or [type(exc).__name__])[0][:400]
            parser.exit(2, "Contest command rejected: " + contest_reason + "\n")
    if args.command == "agent":
        try:
            ledger = AgentLedger(args.database)
            if args.agent_command == "report":
                raw = sys.stdin.buffer.read(16_385)
                if len(raw) > 16_384:
                    raise ValueError("agent report exceeds limit")
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError("agent report must be an object")
                output = ledger.record_report(args.run_id, args.wave_id,
                                              args.assignment_id, payload)
            else:
                output = ledger.synthesize(args.run_id, args.wave_id)
            print(json.dumps(output))
            return 0
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error):
            parser.exit(2, "Agent evidence rejected: use an assigned role, known event references, and abstract text\n")
    if args.command == "web":
        try:
            workflow = WebWorkflow(args.database)
            if args.web_command == "catalog":
                output = workflow.catalog(args.url, token_env=args.token_env,
                                          cookie_env=args.cookie_env, adapter=args.adapter)
            elif args.web_command == "open":
                output = workflow.open(args.url, adapter=args.adapter, challenge_id=args.challenge_id,
                                       allowed_origins=args.allow_origin, token_env=args.token_env,
                                       cookie_env=args.cookie_env, download=not args.no_download,
                                       render=args.render)
            elif args.web_command == "auth":
                private_value = getpass.getpass("Existing CTF " + args.kind + " (stored only in private local state): ")
                if args.kind == "rctf-team-token":
                    output = workflow.rctf_login(args.url, private_value)
                else:
                    output = workflow.auth(args.url, kind=args.kind, value=private_value, scheme=args.scheme)
            elif args.web_command == "context":
                output = workflow.context(args.run_id)
            elif args.web_command == "attest":
                output = workflow.attest(args.run_id, read_candidate(args.candidate_file), verdict=args.verdict,
                                         evidence=args.evidence)
            elif args.web_command == "grant":
                output = workflow.grant_origin(args.run_id, args.url)
            elif args.web_command == "request":
                if args.batch is not None:
                    loaded = json.loads(args.batch.read_bytes()[:8_388_609])
                    entries = loaded.get("requests") if isinstance(loaded, dict) else loaded
                    if not isinstance(entries, list):
                        raise ValueError("batch must be a list of request objects")
                    requests = [WebRequest.model_validate(entry) for entry in entries]
                else:
                    if not args.url:
                        raise ValueError("URL or --batch required")
                    headers = {}
                    for line in args.header:
                        name, separator, value = line.partition(":")
                        if not separator:
                            raise ValueError("header must be 'Name: value'")
                        headers[name.strip()] = value.strip()
                    form_fields: dict[str, str] | None = None
                    if args.form is not None:
                        form_fields = {}
                        for field in args.form:
                            key, separator, value = field.partition("=")
                            if not separator:
                                raise ValueError("form field must be key=value")
                            form_fields[key] = value
                    requests = [WebRequest.model_validate({
                        "url": args.url, "method": args.method.upper(), "headers": headers, "data": args.data,
                        "data_hex": args.data_hex, "form": form_fields,
                        "json": json.loads(args.json_body) if args.json_body is not None else None,
                        "follow": args.follow, "extract": args.extract, "preview": args.preview})]
                output = workflow.request(args.run_id, requests)
            elif args.web_command == "configure-form":
                output = workflow.configure_form(args.run_id, form_index=args.form_index,
                                                 flag_field=args.flag_field, selector=args.selector,
                                                 correct_text=args.correct_text, incorrect_text=args.incorrect_text)
            else:
                output = workflow.submit(args.run_id, read_candidate(args.candidate_file))
            print(json.dumps(output))
            return 0
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error,
                http.client.HTTPException) as exc:
            # Never echo submitted candidates or credentials; METIS validation messages are safe.
            web_reason = ""
            if args.web_command in {"grant", "request", "open", "catalog", "attest"}:
                web_reason = ": " + (str(exc).splitlines() or [type(exc).__name__])[0][:300]
            parser.exit(2, "CTF web command rejected" + web_reason
                        + " (check target scope, credentials, form configuration and limits)\n")
    if args.command == "remote":
        try:
            remote_workflow = RemoteWorkflow(args.database)
            if hasattr(args, "index"):
                args.index = remote_workflow.resolve(args.run_id, args.index)
            if args.remote_command == "suggest":
                output = remote_workflow.suggest(args.run_id)
            elif args.remote_command == "grant":
                output = remote_workflow.grant(args.run_id, args.host, args.port, tls=args.tls,
                                               replace=args.replace)
            elif args.remote_command == "list":
                output = remote_workflow.endpoints(args.run_id)
            elif args.remote_command == "revoke":
                output = remote_workflow.revoke(args.run_id, args.endpoint)
            elif args.remote_command == "connect":
                # stdout carries the raw stream; the summary goes to stderr.
                summary = remote_workflow.connect_stdio(args.run_id, args.index, timeout=args.timeout)
                print(json.dumps(summary), file=sys.stderr)
                return 0
            elif args.remote_command == "ssh":
                password = None
                if args.password_stdin:
                    password = sys.stdin.readline().rstrip("\r\n")
                elif args.password_env:
                    password = os.environ.get(args.password_env)
                    if password is None:
                        raise ValueError("password environment variable is not set")
                remote_input = args.stdin_file.read_bytes()[:1_048_577] if args.stdin_file else b""
                output = remote_workflow.ssh(args.run_id, args.index, username=args.user, password=password,
                                             key_path=args.key, command=args.ssh_command, stdin=remote_input,
                                             downloads=args.get, pty=args.pty, timeout=args.timeout)
            elif args.remote_command == "exchange":
                raw = (args.script.read_bytes()[:1_048_577] if args.script is not None
                       else sys.stdin.buffer.read(1_048_577))
                if len(raw) > 1_048_576:
                    raise ValueError("exchange script exceeds limit")
                output = remote_workflow.exchange(args.run_id, args.index, Exchange.model_validate_json(raw))
            else:
                solver = args.solver[1:] if args.solver[:1] == ["--"] else args.solver
                output = remote_workflow.pipe(args.run_id, args.index, solver, timeout=args.timeout)
            print(json.dumps(output))
            return 0 if output.get("ok", True) else 1
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error) as exc:
            remote_reason = (str(exc).splitlines() or [type(exc).__name__])[0][:300]
            parser.exit(2, "Remote command rejected: " + remote_reason + "\n")
    if args.command == "sandbox":
        try:
            if args.sandbox_command == "status":
                output = sandbox_status(args.database)
            elif args.sandbox_command == "build":
                output = build_image(args.database, engine=args.engine,
                                     platform=None if args.platform == "native" else args.platform)
            elif args.sandbox_command == "configure":
                output = configure(args.database, engine=args.engine, image=args.image,
                                   platform=args.platform)
            else:
                if args.stdin_file is not None and args.stdin_hex is not None:
                    raise ValueError("choose one stdin source")
                stdin = (args.stdin_file.read_bytes()[:1_048_577] if args.stdin_file is not None
                         else bytes.fromhex(args.stdin_hex) if args.stdin_hex is not None else b"")
                script = args.script.read_text()[:262_145] if args.script is not None else None
                output = Sandbox(args.database).execute(args.run_id, SandboxRequest(
                    target=args.target, mode=args.mode, args=args.arg, extra=args.extra, stdin=stdin,
                    gdb=args.gdb, script=script, interpreter=args.interpreter, timeout=args.timeout,
                    emulate=args.emulate))
            print(json.dumps(output))
            return 0 if output.get("ok", True) else 1
        except subprocess.CalledProcessError as exc:
            parser.exit(2, f"Sandbox command failed: the container engine exited with status {exc.returncode};"
                           " see its output above\n")
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error,
                subprocess.SubprocessError) as exc:
            # Messages come from METIS validation or the local engine, not from challenge data.
            sandbox_reason = (str(exc).splitlines() or [type(exc).__name__])[0][:300]
            parser.exit(2, "Sandbox command rejected: " + sandbox_reason + "\n")
    if args.command == "doctor":
        packages: dict[str, str | None] = {}
        for package in ("pydantic", "Pillow", "pyelftools", "capstone", "cryptography", "paramiko"):
            try:
                packages[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                packages[package] = None
        ready = all(packages.values())
        print(json.dumps({"ready": ready, "mode": "codex-native", "api_required": False,
                          "docker_required": False, "packages": packages,
                          "inline_tools": sorted(DATA_TOOLS), "artifact_tools": sorted(ARTIFACT_TOOLS),
                          "optional_system_tools": {name: bool(shutil.which(name)) for name in
                              ("file", "strings", "readelf", "objdump", "gdb", "tshark", "exiftool", "pdftotext")},
                          "binary_execution": "isolated container only (metis sandbox); never on the host",
                          "sandbox": sandbox_status(Path(".metis-state/metis.sqlite")),
                          "remote_services": "metis remote grant/exchange/pipe/connect/ssh for authorized endpoints",
                          "network_route": describe_environment(),
                          "web_adapters": ["html", "ctfd", "rctf", "ksnctf"],
                          "javascript_rendering": browser_available(),
                          "native_network": "offline; explicit target scope required for other Codex tools"}))
        return 0 if ready else 1
    if args.command == "codex":
        try:
            session = CodexSession(args.database)
            if args.codex_command == "demo":
                output = {"sessions": session.demo()}
            elif args.codex_command == "practice":
                output = {"sessions": practice(session), "benchmark": False}
            elif args.codex_command == "board":
                output = {"sessions": session.board(args.limit)}
            elif args.codex_command == "tools":
                output = {"inline_tools": sorted(DATA_TOOLS), "artifact_tools": sorted(ARTIFACT_TOOLS),
                          "artifact_parser_limit_bytes": MAX_ARTIFACT, "artifact_file_limit_bytes": MAX_FILE,
                          "intake_total_limit_bytes": 512 * 1024 * 1024, "inline_limit_bytes": 65_536}
            elif args.codex_command == "plan":
                output = AgentLedger(args.database).create_wave(args.run_id)
            elif args.codex_command == "intake":
                output = session.intake(title=args.title, description=args.description,
                                        paths=args.artifact, categories=args.category,
                                        commitment=args.expected_sha256,
                                        max_actions=args.max_actions, wall_seconds=args.wall_seconds)
            elif args.codex_command == "start":
                manifest = ChallengeManifest.model_validate_json(read_artifact(
                    args.manifest.parent, args.manifest.name,
                ))
                output = session.start(manifest, commitment=args.expected_sha256,
                                       max_actions=args.max_actions, wall_seconds=args.wall_seconds,
                                       artifact_root=args.artifact_root)
            elif args.codex_command in {"artifact", "derive"}:
                if len(args.options.encode()) > 65_536:
                    raise ValueError("options exceed limit")
                options = json.loads(args.options)
                if not isinstance(options, dict):
                    raise ValueError("options must be an object")
                operation = session.artifact if args.codex_command == "artifact" else session.derive
                output = operation(args.run_id, args.name, args.analysis, options)
            elif args.codex_command == "context":
                output = session.context(args.run_id)
            elif args.codex_command == "add-file":
                output = session.add_file(args.run_id, args.path)
            elif args.codex_command == "extend":
                output = session.extend(args.run_id, actions=args.actions, seconds=args.seconds)
            elif args.codex_command == "cancel":
                output = session.cancel(args.run_id)
            elif args.codex_command == "recover":
                output = session.recover(args.run_id)
            else:
                data = (args.data if args.codex_command == "act" and args.data is not None
                        else sys.stdin.buffer.read(65_537).decode())
                if len(data.encode()) > 65_536:
                    raise ValueError("input exceeds limit")
                if args.codex_command == "act":
                    output = session.act(args.run_id, ToolRequest(tool=args.tool, data=data))
                else:
                    output = session.submit(args.run_id, data)
            print(json.dumps(output))
            return 0
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            parser.exit(2, "Codex session command rejected; check scope, state and input limits\n")
    if args.command == "generate-fixtures":
        try:
            if args.oracle.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
                raise ValueError("oracle must not be in the source checkout")
            paths = generate_fixtures(args.directory, args.oracle)
        except (OSError, ValueError):
            parser.exit(2, "fixture generation failed; use a new external private oracle path\n")
        print(json.dumps({"manifests": [str(path) for path in paths]}))
        return 0
    if args.command in {"validate", "prepare", "run"}:
        try:
            manifest = ChallengeManifest.model_validate_json(read_artifact(
                args.manifest.parent, args.manifest.name,
            ))
        except (OSError, ValueError):
            # ValidationError includes rejected input: never echo untrusted secrets.
            parser.exit(2, "manifest rejected: unreadable or invalid manifest\n")
        if args.command == "run":
            try:
                budget = RunBudget(
                    max_actions=args.max_actions, wall_time_seconds=args.wall_time_seconds,
                    per_tool_seconds=args.per_tool_seconds, max_model_tokens=args.max_model_tokens,
                    max_cost_usd=args.max_cost_usd,
                )
                provider: ModelProvider = FixtureProvider()
                if args.provider == "openai":
                    if args.max_call_cost_usd is None:
                        raise ValueError("explicit model call cost reservation required")
                    provider = OpenAIProvider(args.model, max_call_cost_usd=args.max_call_cost_usd)
                oracle = FixtureOracle(args.oracle, solver_roots=(
                    args.manifest.resolve().parent, Path(__file__).resolve().parents[2],
                ))
                store = RunStore(args.database)
                runner = Runner(
                    store, provider, FixtureRuntime(args.image, timeout_seconds=min(
                        args.per_tool_seconds, 60,
                    )), oracle, budget,
                    cancelled=lambda: args.stop_file is not None and args.stop_file.exists(),
                )
                run_id = runner.run(manifest)
                status = store.read(run_id)[-1].status
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                parser.exit(2, "run setup or evidence storage failed\n")
            print(json.dumps({"run_id": run_id, "status": status.value}))
            return 0 if status == RunStatus.SOLVED else 1
        if args.command == "prepare":
            run_id = uuid4().hex
            try:
                store = RunStore(args.database)
                store.append(RunEvent(run_id=run_id, sequence=0, status=RunStatus.NEW))
                store.append(RunEvent(run_id=run_id, sequence=1, status=RunStatus.VALIDATED))
            except (OSError, sqlite3.Error, ValueError):
                parser.exit(2, "run preparation failed\n")
            print(json.dumps({"run_id": run_id, "status": "validated"}))
            return 0
        print(json.dumps({"valid": True, "challenge_id": manifest.challenge_id}))
        return 0
    if args.command == "inspect":
        try:
            history = RunStore(args.database, read_only=True).export_jsonl(args.run_id)
        except (OSError, sqlite3.Error, ValueError):
            parser.exit(2, "run history unavailable or corrupt\n")
        if not history:
            parser.exit(2, "run not found\n")
        print(history, end="")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
