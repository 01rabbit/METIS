# Issue #8 B1: runner hard-token-budget contract and acceptance gate (2026-11-21)

## Purpose

Blocker B1 in the
[#8 blocker inventory](issue8-blocker-inventory-2026-11-21.md) is: *no runner
enforces a hard token budget, so a real-model held-out comparison fails closed.*
This note fixes the **runner contract** — the conditions a runner must meet, and
the evidence it must present, to be authorized for real-model held-out
comparison calls. It is the acceptance gate referenced by B4 requirement R6
([B4 requirements](issue8-b4-protocol-registration-requirements-2026-11-21.md)).
It is a contract spec against the current `main` interfaces; no runner is
changed, no capability is flipped, and no study is run.

## Current enforcement in code (what the gate already checks)

`metis.core.codex_specialist.run_specialist` refuses a bound real-model run
whose prompt is pinned unless one of two paths holds
(`src/metis/core/codex_specialist.py:669-676`):

```
if (heldout prompt_text is set
        and not runner.hard_token_budget_enforced
        and not (admitted_native and study_token_admission is not None)):
    raise ValueError("real-model held-out token cap is not enforceable by this runner")
```

So there are exactly two accepted paths:

- **Path A — a runner that declares `hard_token_budget_enforced = True` and
  enforces it.** The runner implements the `CodexRunner` Protocol
  (`codex_specialist.py:257-263`): `model_turn_budget_enforced`,
  `hard_token_budget_enforced`, and `run(prompt, *, model, timeout, should_stop,
  images) -> CodexTurn`.
- **Path B — the admitted-native seam.** A pinned `LlamaSpecialist` plus a
  `study_token_admission` on this run's native ledger and a callable
  `run_admitted(...)` that consumes a one-time `TokenLaunchClaim`
  (`codex_specialist.py:659-678`, `llama_specialist.py:158+`). The budget is
  governed by the scheduler-mediated atomic admission ledger, not by the flag.

Today **every** runner declares the flag false, with the reason recorded at the
declaration:
- `CodexCLI` (`codex_specialist.py:292`) — "the CLI reports tokens only after a
  turn and has no proven input/output admission limit."
- `LlamaSpecialist` (`llama_specialist.py:47`) — false; it qualifies only
  through Path B.
- `OllamaSpecialist` (`ollama_token_budget.py:215`) — "dispatches by mutable
  tag; a concurrent tag swap can defeat the pre-count."

## The four conditions (C1–C4)

A runner qualifies under Path A only if it truthfully satisfies all four. These
are the conditions `docs/studies/issue8-token-capability.md` requires; this
section binds each to a testable obligation.

### C1 — Proven per-call input and output limit *before* dispatch
The runner must bound both input and output tokens of a call before the model
evaluates any token, not by reading usage after the turn. A post-turn usage
report (CodexCLI) does not satisfy C1. For a local server the output bound is
`n_predict`/`max_output_tokens`; the input bound must be established from the
exact dispatched bytes (e.g. the hashed native request,
`llama_specialist.build_native_request`), and the work actually performed must
be bounded — this is where Path A for the pinned llama arm depends on **B2**
(the unproven token-work bound; `hard_cap_capable=False`).

### C2 — Atomic aggregate reservation across parallel specialists
Concurrent specialists in one run must draw from one aggregate budget reserved
atomically, so two callers cannot each pass a per-call check and jointly exceed
the run cap. Path B realises this in the scheduler's `BEGIN IMMEDIATE`
admission transaction with a one-time consumed claim (replay and concurrent
consumers fail). A Path A runner must provide an equivalent atomic reservation;
a per-call-only check (no shared reservation) fails C2.

### C3 — Reconciliation of reported usage and interruption
After the call the runner must reconcile reported input/output against the
reservation and settle the budget, including on timeout, cancellation, or a
failed call, so abandoned work still charges the budget. `OllamaSpecialist`
settles via `TokenBudget.settle(...)` but cannot bind the dispatch tag, so its
reconciliation is defeatable (fails C3/C2 together).

### C4 — Reject missing or malformed usage (fail closed)
If usage is absent, malformed, or inconsistent with the reservation, the call
is a failure and scores zero; the runner never treats missing usage as zero
cost. This mirrors the held-out finalizer, which rejects observed aggregate use
above the declared cap and never treats missing provider cost as zero.

## Interface obligations

- **Path A runner** implements `CodexRunner` with
  `hard_token_budget_enforced = True`, returns a `CodexTurn` carrying real
  `usage` (input and output), honours `should_stop` and `timeout`, and refuses
  model/image inputs outside its pin.
- **Path B runner** (pinned `LlamaSpecialist`) implements `run_admitted(prompt,
  *, model, timeout, token_claim, admission, ...)`, validates the
  `TokenLaunchClaim`, and passes `assert_heldout_binding` so the dispatched
  backend matches the preregistered pin exactly (`binary_sha256`,
  `model_sha256`, `token_limit`, `max_output_tokens`, `context_reservation`,
  and, when set, `native_manifest_sha256`); the same rendered prompt is hashed
  at admission and sent to the server.

## Acceptance evidence to flip the flag true (not self-declaration)

`hard_token_budget_enforced` may be set true for a runner only with retained,
reproducible evidence that falsifies an upper bound on dispatched token work
under adversarial conditions — prompts at context edges, forced decode retries
and memory failures, timeouts, cancellation, and concurrent callers — matching
the B2 instrumentation plan for the pinned-llama path. A declaration without
this evidence is a contract violation, not a capability. For Path B, the
acceptance evidence is the admission-ledger proof (atomic reservation, one-time
claim consumption, bidirectional reconciliation) already exercised by the native
token-admission tests, plus B2 for the per-call work bound.

## Relationship to other blockers and budget

- C1 (llama arm) and the acceptance evidence depend on **B2** (proven
  token-work bound) and, for concurrency, **B3**.
- This contract is the gate R6 of **B4** enforces before any comparison call.
- **Budget:** zero. This spec defines the contract and the evidence bar; it does
  not implement a runner, flip any flag, or run a study. Flipping a flag true
  requires the acceptance evidence above and is out of scope here.
