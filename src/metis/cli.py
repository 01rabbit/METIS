"""Validate manifests, inspect evidence and run bounded authorized local fixtures."""
from __future__ import annotations

import argparse
import getpass
import http.client
import importlib.metadata
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from metis.core.artifacts import read_artifact
from metis.core.codex_session import CodexSession
from metis.core.contracts import ChallengeManifest, RunBudget, RunEvent, RunStatus
from metis.core.ctf_artifacts import ARTIFACT_TOOLS, MAX_ARTIFACT, MAX_FILE
from metis.core.ctf_knowledge import KnowledgeBase, TechniqueCard
from metis.core.ctf_practice import practice
from metis.core.ctf_tools import DATA_TOOLS
from metis.core.ctf_web import WebWorkflow
from metis.core.fixtures import generate_fixtures
from metis.core.models import FixtureProvider, ModelProvider
from metis.core.openai_provider import OpenAIProvider
from metis.core.runner import Runner
from metis.core.runtime import FixtureRuntime, ToolRequest
from metis.core.store import RunStore
from metis.core.verification import FixtureOracle


def main() -> int:
    output: dict[str, Any]
    parser = argparse.ArgumentParser(prog="metis")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check native CTF tools without API keys or Docker")
    web = sub.add_parser("web", help="generic scoped CTF problem intake and official submission")
    web.add_argument("--database", type=Path, default=Path(".metis-state/metis.sqlite"))
    web_commands = web.add_subparsers(dest="web_command", required=True)
    web_open = web_commands.add_parser("open", help="retrieve problem text and same-origin distribution files")
    web_open.add_argument("url")
    web_open.add_argument("--adapter", choices=("auto", "html", "ctfd", "ksnctf"), default="auto",
                          help="auto recognizes official ksnctf problem URLs; otherwise uses HTML")
    web_open.add_argument("--challenge-id", type=int)
    web_open.add_argument("--allow-origin", action="append", default=[])
    web_open.add_argument("--token-env")
    web_open.add_argument("--cookie-env")
    web_open.add_argument("--no-download", action="store_true")
    auth = web_commands.add_parser("auth", help="privately store an existing CTF cookie or token via a masked terminal prompt")
    auth.add_argument("url")
    auth.add_argument("--kind", choices=("cookie", "token"), required=True)
    auth.add_argument("--scheme", choices=("Token", "Bearer"), default="Token")
    web_context = web_commands.add_parser("context")
    web_context.add_argument("run_id")
    web_submit = web_commands.add_parser("submit", help="submit exact candidate from stdin and inspect the official verdict")
    web_submit.add_argument("run_id")
    form = web_commands.add_parser("configure-form", help="configure a trusted generic POST form before any submission")
    form.add_argument("run_id")
    form.add_argument("--form-index", type=int, required=True)
    form.add_argument("--flag-field", required=True)
    form.add_argument("--selector", required=True)
    form.add_argument("--correct-text", required=True)
    form.add_argument("--incorrect-text", required=True)
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
    for command in ("context", "act", "submit", "cancel", "recover"):
        action = commands.add_parser(command)
        action.add_argument("run_id")
        if command == "act":
            action.add_argument("tool", choices=sorted(DATA_TOOLS))
            action.add_argument("--data", help="omit to read exact UTF-8 input from stdin")
    args = parser.parse_args()

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
    if args.command == "web":
        try:
            workflow = WebWorkflow(args.database)
            if args.web_command == "open":
                output = workflow.open(args.url, adapter=args.adapter, challenge_id=args.challenge_id,
                                       allowed_origins=args.allow_origin, token_env=args.token_env,
                                       cookie_env=args.cookie_env, download=not args.no_download)
            elif args.web_command == "auth":
                private_value = getpass.getpass("Existing CTF " + args.kind + " (stored only in private local state): ")
                output = workflow.auth(args.url, kind=args.kind, value=private_value, scheme=args.scheme)
            elif args.web_command == "context":
                output = workflow.context(args.run_id)
            elif args.web_command == "configure-form":
                output = workflow.configure_form(args.run_id, form_index=args.form_index,
                                                 flag_field=args.flag_field, selector=args.selector,
                                                 correct_text=args.correct_text, incorrect_text=args.incorrect_text)
            else:
                candidate_bytes = sys.stdin.buffer.read(65_537)
                if candidate_bytes.endswith(b"\r\n"):
                    candidate_bytes = candidate_bytes[:-2]
                elif candidate_bytes.endswith(b"\n"):
                    candidate_bytes = candidate_bytes[:-1]
                candidate = candidate_bytes.decode()
                output = workflow.submit(args.run_id, candidate)
            print(json.dumps(output))
            return 0
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error,
                http.client.HTTPException):
            parser.exit(2, "CTF web command rejected: check target scope, credentials, form configuration and limits\n")
    if args.command == "doctor":
        packages: dict[str, str | None] = {}
        for package in ("pydantic", "Pillow", "pyelftools", "capstone", "cryptography"):
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
                          "binary_execution": "not provided by native data tools",
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
