# Issue #6 candidate/report single-turn handoff

## Scope

This controller change allows a specialist to return a private candidate and its final compact report in one Codex turn. It targets the call-starvation hypothesis raised by the symmetric replication. It does not change the frozen benchmark, establish that call starvation caused the result, or demonstrate a performance gain.

## Behavior and privacy

- The existing separate `candidate` then `report` sequence remains supported.
- `candidate_report` checks the report against the proposed value and all pending or previously proposed candidates before accepting it.
- Candidate values remain in process memory for retry checks or in the existing private candidate file. They are excluded from reports, scheduler events, test output and returned summaries.
- A rejected combined report does not consume a candidate slot. Retrying a scheduler-rejected report with the same pending candidate reuses that candidate instead of storing a duplicate.
- Candidate disclosure checks traverse decoded report strings, including nested fields. A report-only retry is checked against candidates proposed earlier in the same assignment, even if the initial combined response was rejected before storage.

## Verification

- `pytest -q tests/test_codex_specialist.py` — 40 passed.
- Full `.venv/bin/pytest -q` reached 100% with no failures.
- `.venv/bin/ruff check src/metis/core/codex_specialist.py tests/test_codex_specialist.py` — passed.
- `.venv/bin/mypy src/metis/core/codex_specialist.py` — passed.
- `git diff --check` — passed.

Focused regressions cover same-turn completion, legacy separate handoff, nested and escaped candidate disclosure, immediate report-only retry after rejected combined submission, and repeated scheduler-level report rejection without duplicate candidate storage.

## Remaining acceptance work

This is an implementation optimization only. Issue #6 still needs a separate preregistered comparison that controls specialist count, concurrency and model-call cap, and reports workflow completion, latency, calls, and uncertainty. The earlier symmetric replication remains the current benchmark evidence and is negative for multi-agent workflow completion.
