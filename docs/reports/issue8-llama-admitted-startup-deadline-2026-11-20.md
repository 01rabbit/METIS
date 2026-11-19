# Issue #8: bound admitted llama startup by call deadline (2026-11-20)

The scheduler-admitted `LlamaSpecialist` now computes one monotonic call
deadline before native server startup and passes it, with the run stop callback,
into the backend. Health polling checks cancellation between attempts, caps each
health request by the remaining deadline, and terminates the process group on
cancellation or timeout. Tokenization and completion share the same deadline;
time spent starting the server cannot extend the admitted call budget. A
startup cancellation records a cancelled terminal outcome, while deadline
expiry records a timeout. The already-consumed token reservation is retained.

Validation on the PR branch:

```text
PYTHONPATH=src:. /Users/mao/Developer/GitHub/METIS/.venv/bin/pytest -q tests/test_llama_server_backend.py tests/test_llama_specialist.py
54 passed
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
access. Additional tests ensure an already-cancelled or expired call does not
hash or launch the server. This does not demonstrate a real model hard token
cap, provider billing limits, or held-out benchmark improvement.
`LlamaSpecialist.hard_token_budget_enforced` remains false and Issue #8 remains
open.

The test interpreter was Python 3.12.13 on the local Apple Silicon macOS host.
