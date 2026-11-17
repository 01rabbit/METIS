# Issue #6 run-wide model-turn reservation (2026-11-17)

## Change

The scheduler snapshots a finite per-run Codex model-invocation limit when the
first wave is enqueued (default 24; configurable from 1 to 256 with
`metis agent slots --specialist-turn-budget N`). Each `run_assignment` provider
call reserves one turn in a SQLite `BEGIN IMMEDIATE` transaction before the
provider is invoked. A reservation records run, assignment, attempt, and time.
If the shared limit is exhausted, the assignment is failed before another model
call. Reservations survive scheduler reconstruction and are not refunded for
failed calls or retries. Later configuration changes affect new runs only.

The tests exercise parallel reservation of the final shared slots, immutable
per-run configuration, and refusal to call the provider after exhaustion.
Existing concurrency, cancellation, intent-budget, orchestration, autopilot,
and specialist tests were run together.

## Validation

```text
.venv/bin/pytest -ra tests/test_agent_orchestration.py tests/test_codex_specialist.py tests/test_agent_autopilot.py
53 passed in 4.75s
.venv/bin/ruff check src/metis/core/agent_scheduler.py src/metis/core/codex_specialist.py src/metis/cli.py tests/test_agent_orchestration.py tests/test_codex_specialist.py
All checks passed!
.venv/bin/mypy src/metis
Success: no issues found in 51 source files
```

## Limits and unmet gate

This reserves Codex call attempts made through the `CodexCLI` driver. A
reservation is conservative: process cancellation can occur after reservation
but before the provider call starts. The
`BridgeHost` path asks Daybreak to run host-native subagents directly, outside
METIS's provider-call boundary; METIS cannot reserve or stop those hidden model
turns. Provider token/cost usage is post-call and may be absent, so this change
does not claim a hard token cap; missing usage remains `unknown`.

Bounded autopilot now requires its runner to explicitly advertise the
controller-side model-turn reservation contract. A runner without that
capability stops before dispatch with `host_model_turn_budget_unenforced` and
reports `budget_enforcement: unavailable`. The production `CodexCLI` runner
advertises the contract; the direct/manual `BridgeHost` subagent route remains
outside bounded-autopilot guarantees.

No controlled real-model single-agent versus multi-agent benchmark has been
run. The synthetic scheduler tests prove only reservation, race behavior, and
failure-before-call mechanics. Issue #6 remains open until a controlled,
matched-budget comparison is run and reviewed, and host-native turn/token
limitations are resolved or explicitly bounded by the operating path.
