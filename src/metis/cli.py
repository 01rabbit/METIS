"""Validate manifests, inspect evidence and run bounded authorized local fixtures."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

from metis.core.artifacts import read_artifact
from metis.core.codex_session import CodexSession
from metis.core.contracts import ChallengeManifest, RunBudget, RunEvent, RunStatus
from metis.core.fixtures import generate_fixtures
from metis.core.models import FixtureProvider, ModelProvider
from metis.core.openai_provider import OpenAIProvider
from metis.core.runner import Runner
from metis.core.runtime import FixtureRuntime, ToolRequest
from metis.core.store import RunStore
from metis.core.verification import FixtureOracle


def main() -> int:
    parser = argparse.ArgumentParser(prog="metis")
    sub = parser.add_subparsers(dest="command", required=True)
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
    codex.add_argument("--database", type=Path, required=True)
    commands = codex.add_subparsers(dest="codex_command", required=True)
    commands.add_parser("demo", help="create two local puzzles without plaintext answer storage")
    start = commands.add_parser("start", help="start an inline authorized local puzzle")
    start.add_argument("manifest", type=Path)
    start.add_argument("--expected-sha256")
    start.add_argument("--max-actions", type=int, default=40)
    start.add_argument("--wall-seconds", type=int, default=1200)
    for command in ("context", "act", "submit", "cancel"):
        action = commands.add_parser(command)
        action.add_argument("run_id")
        if command == "act":
            action.add_argument("tool", choices=("base64_decode", "hex_decode", "sha256"))
            action.add_argument("--data", help="omit to read exact UTF-8 input from stdin")
    args = parser.parse_args()

    if args.command == "codex":
        try:
            session = CodexSession(args.database)
            if args.codex_command == "demo":
                output = {"sessions": session.demo()}
            elif args.codex_command == "start":
                manifest = ChallengeManifest.model_validate_json(read_artifact(
                    args.manifest.parent, args.manifest.name,
                ))
                output = session.start(manifest, commitment=args.expected_sha256,
                                       max_actions=args.max_actions, wall_seconds=args.wall_seconds)
            elif args.codex_command == "context":
                output = session.context(args.run_id)
            elif args.codex_command == "cancel":
                output = session.cancel(args.run_id)
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
