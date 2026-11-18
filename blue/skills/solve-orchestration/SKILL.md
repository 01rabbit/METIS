---
name: solve-orchestration
description: Operate the METIS worker pool, dependencies, resource admission and task recovery for parallel defensive evidence analysis.
---

# Worker pool operations

Read `skills/blue-owner/SKILL.md` and `docs/runtime.md`. The owner remains the entry point and
main operator. Analysis workers share a continuous ready queue, not fixed waves.

`metis blue run "investigation objective" --provider claude --model claude-opus-4-6`
uses one owner planning call, the bounded pool and one owner reporting call.
`--plan examples/offline-plan.json` supplies a deterministic DAG. `--provider mock` exercises
scheduling only and never claims real analysis. `--workers` and `--provider-limit` bound
parallelism; `METIS_BLUE_PROVIDER_WORKERS` supplies an environment-specific quota.

For native Codex/Claude agents, use `prepare`, save the run ID, `claim` before each dispatch,
and `finish` after the worker has actually stopped. `claim` atomically reserves all resources.
Do not use a separate in-memory semaphore that disagrees with SQLite. The database is shared
across runs. A blocked SIEM task does not prevent another ready CPU-only task from starting.

Split collection, evidence interpretation, verification and user-visible action where this
releases scarce resources earlier. Account for browser session width, SIEM search width, VM
count, disk, memory, model quota and service rate limits independently. Report missing capacity
before dispatch; do not guess that a read is inexpensive. Use a dependency when work needs
another result. Failed dependencies block descendants and never count as completed analysis.

A process crash leaves leases reserved. Before recovery, the owner verifies that every affected
process and remote job is stopped. Never expire a lock merely because a timer elapsed: the old
worker could still be running. Pending tasks can be resumed; failed or uncertain writes require
reconciliation before a new task is created. Never repeat a submission with an unknown outcome.

Attach the exact input path/hash, record selection and required return fields using [evidence locators](../soc-triage/references/evidence-locators.md). Preserve `run_id`/task identity separately from the soclog case ID; use [CLI state and fields](../../docs/cli-reference.md) to reconcile claims and results.
