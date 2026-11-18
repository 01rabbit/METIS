# Phase 4 specialist-driver exception handoff (2026-11-18)

## Change

If a specialist future raises inside the bounded autopilot, the controller now
discards exception text, records the answer-free stop reason
`specialist_driver_exception`, completes the bounded synthesis/metrics path,
and marks one Daybreak handoff. It leaves the attempt states unchanged because
the exception does not prove an external worker has stopped. Queued siblings
remain queued; running or unknown attempts block a resumed autopilot before
dispatch, so the invocation does not launch duplicate work.

## Validation

The synthetic fault-injection test raises a private-text exception from every
driver. It confirms the returned result omits the exception text, the stop and
handoff counters are persisted in `agent_autopilot_runs`, running attempts are
retained, queued siblings are not advanced, and a second invocation stops for
reconciliation without increasing attempt numbers.

A second mixed-batch test completes one sibling, reserves a model turn for a
second sibling and then raises, leaving two more assignments queued. It
confirms the reservation remains charged after the exception and resume, and
that `specialist_turns` reports and persists the invocation's reservation
count instead of losing the interrupted call.

`agent_turn_reservations` does not currently store an autopilot invocation ID.
The counter is scoped to the run, assignments observed in this invocation's
waves, and reservation timestamps within the invocation window. A concurrent
manual action on one of those same assignments cannot be attributed separately
by this schema; this remains a controller-side count, not provider usage.

```text
.venv/bin/pytest -q tests/test_agent_autopilot.py tests/test_stay_header_differential.py tests/test_ctf_zipcrypto.py::test_infozip_seed_recovers_every_random_header_byte
14 passed
.venv/bin/ruff check src/metis/core/agent_autopilot.py tests/test_agent_autopilot.py tests/test_stay_header_differential.py
All checks passed!
.venv/bin/mypy src/metis/core/agent_autopilot.py
Success: no issues found in 1 source file
git diff --check
```

The all-crash injection occurs before specialist work is charged. The mixed
test reserves one controller-side model turn, but contacts no provider and does
not measure actual token use. No exception is interpreted as proof of worker
termination, no automatic retry is made, and these synthetic results do not
establish host liveness or recovery.
