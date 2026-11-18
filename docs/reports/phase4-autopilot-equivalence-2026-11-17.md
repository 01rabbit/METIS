# Phase 4 bounded autopilot control-flow comparison (2026-11-17)

## Method

Two fresh SQLite databases ran the same synthetic challenge setup with two
categories, two registered artifacts, four specialist assignments, and a
two-slot per-run cap. A fixed test driver completed every assignment with an
inconclusive synthetic report referencing an existing event. The comparison
ran one wave through direct scheduler calls and one through `autopilot`; neither
used a model, Docker, live CTF, or candidate answer.

## Observed result

The direct controller sequence called plan once, enqueue once, dispatch twice
for its two parallel batches, and synthesis once. It started four specialist
assignments and retried none. Autopilot returned the same operation counts:

| Operation | Direct calls | Autopilot counter |
| --- | ---: | ---: |
| Plan created | 1 | 1 |
| Enqueue | 1 | 1 |
| Dispatch batches | 2 | 2 |
| Spawn retry | 0 | 0 |
| Synthesis | 1 | 1 |
| Continuation created | 0 | 0 |
| Specialists started | 4 | 4 |

Both paths produced complete one-wave syntheses with four inconclusive
reports. Autopilot stopped at `wave_limit` and marked one Daybreak handoff.
All returned metric fields matched the persisted SQLite record. The five direct
calls count plan/enqueue/dispatch/synthesis control operations; they exclude the
fixed driver's `complete` report-delivery calls. A separate
zero-specialist sequential case records token usage as `unknown`, not zero,
and verifies the same value is persisted.

This establishes control-flow and counter equivalence for a deterministic
synthetic case. It shows that one bounded autopilot invocation can package the
same plan/enqueue/dispatch/synthesize choreography as five direct controller
calls. The test driver is fixed and synthetic; the result does not measure real
human time, actual Daybreak work, adaptive reasoning, solve rate, or live
specialist behavior. Continuation selection and all scope/submission/auth
decisions remain with Daybreak.

## Reproduction

```text
.venv/bin/pytest -ra tests/test_agent_autopilot.py
7 passed in 0.42s
.venv/bin/ruff check src/metis/core/agent_autopilot.py tests/test_agent_autopilot.py
All checks passed!
.venv/bin/mypy src/metis
Success: no issues found in 51 source files
```
