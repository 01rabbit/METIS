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

from metis.blue import journal
from metis.core.resources import ResourceBroker, ScopedPermits, init_owner_key, read_owner_key

DEFAULT_DATABASE = Path(".metis-state/metis.sqlite")


def register(sub: Any) -> None:
    resource = sub.add_parser("resource", help="shared capacities (sandbox, browser, ...) leased atomically")
    resource.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    commands = resource.add_subparsers(dest="resource_command", required=True)
    commands.add_parser("status", help="capacities, leased units and current leases")
    configure = commands.add_parser("configure", help="owner: set a capacity; --unlimited removes it")
    configure.add_argument("name")
    group = configure.add_mutually_exclusive_group(required=True)
    group.add_argument("--capacity", type=int)
    group.add_argument("--unlimited", action="store_true")
    release = commands.add_parser("release", help="owner: free a lease whose holder you confirmed stopped")
    release.add_argument("lease_id")
    release.add_argument("--reason", required=True, help="how the holder was confirmed stopped")
    commands.add_parser("reap", help="free expired leases whose holder process is confirmed gone; "
                        "others are kept and listed")
    for command in (configure, release):
        command.add_argument("--owner-key-file", type=Path,
                             help="default <state dir>/private/owner.key, or $METIS_OWNER_KEY")

    permit = sub.add_parser("permit", help="exact, expiring, counted authority for state-changing actions")
    permit.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    permit_commands = permit.add_subparsers(dest="permit_command", required=True)
    permit_commands.add_parser("init", help="owner: create the owner key once (0600; only its digest is stored)")
    issue = permit_commands.add_parser("issue", help="Daybreak/owner only: authorize one exact action")
    issue.add_argument("run_id")
    issue.add_argument("task")
    issue.add_argument("resource")
    issue.add_argument("action")
    issue.add_argument("--reason", required=True)
    issue.add_argument("--ttl", type=int, default=300)
    issue.add_argument("--uses", type=int, default=1)
    issue.add_argument("--owner-key-file", type=Path,
                       help="default <state dir>/private/owner.key, or $METIS_OWNER_KEY")
    listing = permit_commands.add_parser("list")
    listing.add_argument("--run-id")
    revoke = permit_commands.add_parser("revoke")
    revoke.add_argument("permit_id")


    journal_parser = sub.add_parser("journal", help="private case journal: notes, queries, findings, lessons")
    journal_parser.add_argument("--root", help="journal directory (default .metis-state/journal or "
                                "$METIS_JOURNAL_ROOT)")
    journal.add_commands(journal_parser.add_subparsers(dest="journal_command", required=True),
                         journal.JournalArgumentParser)


def handle(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int | None:
    output: dict[str, Any]
    if args.command == "resource":
        try:
            broker = ResourceBroker(args.database)
            if args.resource_command == "status":
                output = broker.status()
            elif args.resource_command == "configure":
                output = broker.configure(args.name, None if args.unlimited else args.capacity,
                                          owner_key=read_owner_key(args.database, args.owner_key_file))
            elif args.resource_command == "release":
                output = {"lease_id": args.lease_id, "released": broker.force_release(
                    args.lease_id, owner_key=read_owner_key(args.database, args.owner_key_file), reason=args.reason)}
            else:
                output = broker.reap()
        except (OSError, ValueError, PermissionError, sqlite3.Error) as exc:
            parser.exit(2, "Resource command rejected: " + str(exc)[:300] + "\n")
        print(json.dumps(output))
        return 0
    if args.command == "permit":
        try:
            permits = ScopedPermits(args.database)
            if args.permit_command == "init":
                output = init_owner_key(args.database)
            elif args.permit_command == "issue":
                output = permits.issue(args.run_id, args.task, args.resource, args.action, args.reason,
                                       owner_key=read_owner_key(args.database, args.owner_key_file),
                                       ttl=args.ttl, uses=args.uses)
            elif args.permit_command == "list":
                output = {"permits": permits.list(args.run_id)}
            else:
                output = {"permit_id": args.permit_id, "revoked": permits.revoke(args.permit_id)}
        except (OSError, ValueError, PermissionError, sqlite3.Error) as exc:
            parser.exit(2, "Permit command rejected: " + str(exc)[:300] + "\n")
        print(json.dumps(output))
        return 0
    if args.command == "journal":
        values = {key: value for key, value in vars(args).items() if key not in {"command", "root"}}
        values["command"] = values.pop("journal_command")
        return journal.run(argparse.Namespace(**values), journal.journal_root(args.root))
    return None
