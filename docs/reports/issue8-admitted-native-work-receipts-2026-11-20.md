# Admitted native work receipts

This increment connects the scheduler-consumed held-out admission to the
prototype's nonce-bound native work cap. A fresh per-process cap equals the
committed token allowance minus the maximum output headroom. The native binary
receives the cap, private Unix socket, receipt pipe descriptor and fresh nonce
at launch. On process exit the controller requires exactly one bounded JSON
receipt whose nonce, cap, charged work, reason and process status agree.

The terminal receipt is now the source of `observed_work`. A missing, malformed,
duplicated, oversized or mismatched record fails closed; admission charges are
never refunded. Cap denial, unsupported graph work and native server failure
are retained as distinct terminal outcomes. Startup, cancellation and deadline
cleanup continue to use the existing bounded process-group lifecycle.

The implementation remains deliberately unqualified: both
`LlamaServerBackend.hard_cap_capable` and
`LlamaSpecialist.hard_token_budget_enforced` remain false. The counter in the
custom llama.cpp patch measures submitted graph token positions, not provider
billing tokens, model-load allocations, arbitrary graph paths or other model
runtimes. Tests use a local fake binary and make no model, provider or CTF
calls. The public `stories260K.gguf` fixture qualification is separate evidence
and does not generalize to held-out models. Issue #8 remains open.

## Validation

- Focused admitted-backend suites: 104 tests passed across
  `tests/test_llama_server_backend.py`, `tests/test_llama_specialist.py`, and
  `tests/test_heldout_token_admission.py`.
- ZipCrypto deterministic intent-chain and registration checks: 2 passed.
- Ruff: passed on changed Python and documentation paths.
- Mypy: passed on `llama_server_backend.py` and `llama_specialist.py`.
- `scripts/check_repo.py`: passed with 0 findings; `git diff --check`: passed.
- The optional real patched-binary fixture was not run because this host has no
  running Docker engine. No real model was launched.

The existing sandbox CI had one variable-timeout failure in a full 300-second
ZipCrypto test. The worker now uses four processes to match the sandbox's
four-CPU quota rather than oversubscribing it with eight. The deterministic
local tests pass; the full container search remains for exact-head CI to
recheck. Failure diagnostics now retain only status, reason, stage, and elapsed
time, not recovered key material.
