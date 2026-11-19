# Issue #8: bound llama startup by call deadline (2026-11-20)

Both `LlamaSpecialist.run()` and the scheduler-admitted `run_admitted()` compute
one monotonic call deadline before native server startup and pass it, with the
run stop callback, into the backend. Health polling uses the same bounded,
cancellable request path as tokenization and completion. Artifact hashing and
the shared SQLite reservation check the deadline and cancellation between
bounded operations, and expiry is checked immediately before the child process
is launched. The backend terminates the process group on cancellation or
timeout. A startup cancellation records a cancelled outcome, while deadline
expiry records a timeout. An admitted token reservation already committed by
the scheduler is retained.

Validation on the PR branch:

```text
PYTHONPATH=src:. /Users/mao/Developer/GitHub/METIS/.venv/bin/pytest -q tests/test_llama_server_backend.py tests/test_llama_specialist.py
63 passed
ruff check src tests scripts
All checks passed
mypy src
Success: no issues found in 113 source files
python scripts/check_repo.py
{"status":"passed","findings":0}
git diff --check
passed
```

The fake server fixture delays startup and trickles health-response bytes to
verify cancellation and deadline cleanup without model inference or network
access; a marker confirms each probe reached the trickling response. Additional
tests verify cancellation during a multi-chunk artifact hash and while waiting
on a locked budget database, and prevent child launch after deadline expiry.
This does not demonstrate a real model hard token cap, provider billing limits,
or held-out benchmark improvement.
`LlamaSpecialist.hard_token_budget_enforced` remains false and Issue #8 remains
open.

The test interpreter was Python 3.12.13 on the local Apple Silicon macOS host.
