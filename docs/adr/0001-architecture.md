# ADR 0001 — Separate controller, executor and verifier

Status: Accepted for P0 implementation.

Decision: Python controller with typed model-provider adapter, authorization and tool broker. Use separately isolated Linux tool runtime and independent verifier with no answer-store exposure. Store persistent state in SQLite + append-only JSONL.

Rationale: lower coupling, auditable agent loop, benchmark validity, safe macOS hosting, and replaceable models. Do not make Codex itself the only runtime dependency.

Consequences: more explicit interfaces and integration tests; inability to claim solved from candidate flag alone. Multi-agent orchestration is deferred until P1 baseline is measured.
