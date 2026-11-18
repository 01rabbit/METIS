"""CLI commands, kept out of ``cli.py`` so each capability stays reviewable.

``register`` adds the subcommands; ``handle`` returns an exit code when it owns the command, or
``None`` so ``cli.main`` continues with its own dispatch.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from metis.blue import connections, evidence, journal, siem
from metis.blue.ledger import ConnectionLedger
from metis.core.resources import ResourceBroker, ScopedPermits

DEFAULT_DATABASE = Path(".metis-state/metis.sqlite")


def register(sub: Any) -> None:
    resource = sub.add_parser("resource", help="shared capacities (sandbox, browser, ...) leased atomically")
    resource.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    commands = resource.add_subparsers(dest="resource_command", required=True)
    commands.add_parser("status", help="capacities, leased units and current leases")
    configure = commands.add_parser("configure", help="set a capacity; --unlimited removes it")
    configure.add_argument("name")
    group = configure.add_mutually_exclusive_group(required=True)
    group.add_argument("--capacity", type=int)
    group.add_argument("--unlimited", action="store_true")
    release = commands.add_parser("release", help="release a lease whose holder has confirmed stopped")
    release.add_argument("lease_id")
    commands.add_parser("reap", help="release expired leases (only after their holders are gone)")

    permit = sub.add_parser("permit", help="exact, expiring, counted authority for state-changing actions")
    permit.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    permit_commands = permit.add_subparsers(dest="permit_command", required=True)
    issue = permit_commands.add_parser("issue", help="Daybreak/owner only: authorize one exact action")
    issue.add_argument("run_id")
    issue.add_argument("task")
    issue.add_argument("resource")
    issue.add_argument("action")
    issue.add_argument("--reason", required=True)
    issue.add_argument("--ttl", type=int, default=300)
    issue.add_argument("--uses", type=int, default=1)
    listing = permit_commands.add_parser("list")
    listing.add_argument("--run-id")
    revoke = permit_commands.add_parser("revoke")
    revoke.add_argument("permit_id")


    journal_parser = sub.add_parser("journal", help="private case journal: notes, queries, findings, lessons")
    journal_parser.add_argument("--root", help="journal directory (default .metis-state/journal or "
                                "$METIS_JOURNAL_ROOT)")
    journal.add_commands(journal_parser.add_subparsers(dest="journal_command", required=True),
                         journal.JournalArgumentParser)
    evidence_parser = sub.add_parser("evidence", help="bounded offline evidence reader for a local file "
                                     "(email, browser, json, cloudtrail, evtx-xml)")
    evidence.add_arguments(evidence_parser)
    siem_parser = sub.add_parser("siem", help="bounded Splunk/Elastic read searches inside a task lease")
    siem.add_arguments(siem_parser)

    lease = sub.add_parser("lease", help="Daybreak only: lease resources to a task, or finish it")
    lease.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    lease_commands = lease.add_subparsers(dest="lease_command", required=True)
    grant_lease = lease_commands.add_parser("task", help="lease NAME=UNITS resources to RUN/TASK")
    grant_lease.add_argument("run")
    grant_lease.add_argument("task")
    grant_lease.add_argument("resources", nargs="+", help="NAME=UNITS")
    grant_lease.add_argument("--ttl", type=int, default=3600)
    finish = lease_commands.add_parser("finish", help="release a task's leases (refused while connected)")
    finish.add_argument("run")
    finish.add_argument("task")
    report = lease_commands.add_parser("report", help="connections and redacted messages of a run")
    report.add_argument("run")

    connect = sub.add_parser("connect", help="SSH/RDP/VNC/SOCKS/VPN profile: show the plan, or --execute it")
    connect.add_argument("profile")
    connect.add_argument("--profiles", type=Path, default=Path(".metis-state/connections.json"))
    connect.add_argument("--action", required=True)
    connect.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    connect.add_argument("--run")
    connect.add_argument("--task")
    connect.add_argument("--permit", help="scoped permit for state-changing actions (desktop, tunnel, control)")
    connect.add_argument("--execute", action="store_true")
    connect.add_argument("--timeout", type=int, default=60)


def handle(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int | None:
    output: dict[str, Any]
    if args.command == "resource":
        try:
            broker = ResourceBroker(args.database)
            if args.resource_command == "status":
                output = broker.status()
            elif args.resource_command == "configure":
                output = broker.configure(args.name, None if args.unlimited else args.capacity)
            elif args.resource_command == "release":
                output = {"lease_id": args.lease_id, "released": broker.release(args.lease_id, reason="operator")}
            else:
                output = {"reaped": broker.reap()}
        except (OSError, ValueError, sqlite3.Error) as exc:
            parser.exit(2, "Resource command rejected: " + str(exc)[:300] + "\n")
        print(json.dumps(output))
        return 0
    if args.command == "permit":
        try:
            permits = ScopedPermits(args.database)
            if args.permit_command == "issue":
                output = permits.issue(args.run_id, args.task, args.resource, args.action, args.reason,
                                       ttl=args.ttl, uses=args.uses)
            elif args.permit_command == "list":
                output = {"permits": permits.list(args.run_id)}
            else:
                output = {"permit_id": args.permit_id, "revoked": permits.revoke(args.permit_id)}
        except (OSError, ValueError, sqlite3.Error) as exc:
            parser.exit(2, "Permit command rejected: " + str(exc)[:300] + "\n")
        print(json.dumps(output))
        return 0
    if args.command == "journal":
        values = {key: value for key, value in vars(args).items() if key not in {"command", "root"}}
        values["command"] = values.pop("journal_command")
        return journal.run(argparse.Namespace(**values), journal.journal_root(args.root))
    if args.command == "siem":
        return int(siem.run(args))
    if args.command == "lease":
        try:
            ledger = ConnectionLedger(args.database)
            if args.lease_command == "task":
                wanted: dict[str, int] = {}
                for item in args.resources:
                    name, _, units = item.partition("=")
                    wanted[name] = int(units or "1")
                output = {"lease_id": ledger.lease_task(args.run, args.task, wanted, ttl=args.ttl)}
            elif args.lease_command == "finish":
                output = {"released": ledger.finish_task(args.run, args.task)}
            else:
                output = ledger.report(args.run)
        except (OSError, ValueError, PermissionError, sqlite3.Error) as exc:
            parser.exit(2, "Lease command rejected: " + str(exc)[:300] + "\n")
        print(json.dumps(output, default=str))
        return 0
    if args.command == "connect":
        try:
            config = connections.profile(args.profiles, args.profile)
            if not args.execute:
                spec = connections.build(config, args.action)
                spec.pop("env", None)
                spec.pop("stdin", None)
                print(json.dumps(spec))
                return 0
            if not args.run or not args.task:
                raise ValueError("execution requires --run and --task")
            result = connections.execute(ConnectionLedger(args.database), args.run, args.task, config, args.action,
                                         args.permit, args.timeout)
        except (OSError, ValueError, KeyError, PermissionError, sqlite3.Error) as exc:
            parser.exit(2, "Connection rejected: " + str(exc)[:300] + "\n")
        print(json.dumps(result))
        return 2 if result.get("timed_out") or result.get("returncode", 0) else 0
    if args.command == "evidence":
        return int(evidence.run(args))
    return None
