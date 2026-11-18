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
    return None
