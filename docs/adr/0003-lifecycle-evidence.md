# ADR 0003 — Fail-closed contracts and controller lifecycle evidence

Status: Accepted for this increment; P0 acceptance remains incomplete.

Scope: local fixtures and explicitly authorized CTF infrastructure.

Decisions:

- Reject unknown contract fields, non-finite budgets and coerced authorization.
  Use portable relative artifact paths and exact ASCII hostname/IP syntax.
  An endpoint declaration is not a network grant implementation: DNS resolution,
  address pinning and enforcement belong to the future execution broker.
- Persist lifecycle events in controller-owned SQLite with transactional sequence
  allocation, explicit transitions, and terminal-state enforcement. Concurrent
  writers cannot both commit the same sequence. Inspection uses read-only access.
- SQLite is authoritative. JSONL is a validated export, avoiding non-atomic dual
  writes. Hash chains detect accidental payload corruption; they do not protect
  against an attacker controlling the database and code. Update/delete triggers
  prevent ordinary application mutations, not privileged database edits.
- Keep secrets, flags and raw tool output out of event details. CLI validation
  errors omit rejected input because Pydantic errors can otherwise disclose it.
  This increment provides no general-purpose automatic secret redactor.
- `metis prepare` records NEW and VALIDATED only. It does not execute tools,
  contact a model, inspect artifact contents or claim a solve. Failure between
  these appends can leave an auditable NEW run; automatic resume is not implemented.

Additional implemented prerequisites: descriptor-based artifact reads reject
symlinks, nonregular files and oversized content. Artifacts are handed off as
bytes, not mutable host paths. A digest-pinned Python container implements only
three fixed transforms, without host mounts, network or arbitrary command input.
Its CPU, memory, PID and wall-time limits are enforced by Docker/the controller.
Timeout cleanup is explicit and unconfirmed cleanup is an infrastructure error.
This introduces a restricted fixture execution boundary, not a general binary
sandbox or a claim of kernel-escape resistance. No existing permissions are
broadened. A protected verifier protocol and adversarial isolation review remain.

Consequences: deterministic contract, lifecycle and fixture-runtime tests are
possible without model credentials. A complete solver/verifier protocol, global
budget/cancellation enforcement and real-provider tests remain required before
P0/P1 acceptance.
