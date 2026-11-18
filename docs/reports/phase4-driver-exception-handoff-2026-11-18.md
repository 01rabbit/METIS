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

```text
.venv/bin/pytest -q tests/test_agent_autopilot.py tests/test_stay_header_differential.py tests/test_ctf_zipcrypto.py::test_infozip_seed_recovers_every_random_header_byte
13 passed
.venv/bin/ruff check src/metis/core/agent_autopilot.py tests/test_agent_autopilot.py tests/test_stay_header_differential.py
All checks passed!
.venv/bin/mypy src/metis/core/agent_autopilot.py
Success: no issues found in 1 source file
git diff --check
```

The failure injection occurs before any specialist work is charged and does not
test a mixed completed/crashed sibling batch or preservation of spent budget.
No exception is interpreted as proof of worker termination, no automatic retry
is made, and this synthetic result does not establish host liveness or recovery.
