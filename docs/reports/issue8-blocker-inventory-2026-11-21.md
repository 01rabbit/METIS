# Issue #8 blocker inventory (2026-11-21)

## Purpose

Issue #8 (choose the METIS configuration that most successfully solves the
owner's CTF tasks within a time and model-use budget) is accepted only when
recorded end-to-end trials count **verified solves only** and support a
practical settings choice. The central unmet step is running that comparison.
This note inventories, against the current `main` tree, the prerequisite
blockers that prevent the comparison from being run and interpreted, with their
state, clearing condition, dependency, and whether model-use budget is needed.
It is a stock-take, not a preregistration and not a gain claim.

## Source of truth

All file and flag references below were checked against remote `origin/main`
(local `main` equals `origin/main`). The one remaining remote work branch,
`codex/issue8-conservative-bound`, was inspected and is described under
"Remaining remote branch" below. No model call or study run was made.

## Blockers

### B1 — No runner enforces a hard token budget (central gate)

- **State:** every runner declares the capability false and the held-out path
  fails closed without it.
  - `src/metis/core/codex_specialist.py:292` `hard_token_budget_enforced = False`
  - `src/metis/core/llama_specialist.py:47` false; `:115`/`:165` `hard_cap_capable: False`
  - `src/metis/core/ollama_token_budget.py:215` `hard_token_budget_enforced = False`
- **Evidence:** `docs/studies/issue8-token-capability.md` — a post-turn usage
  report cannot make an already-dispatched call fit the cap. The 2026-11-19
  exploratory Rev study exceeded its declared 50,000-token cap in every run.
- **Clearing condition:** an authorized runner that proves (1) per-call input
  and output limits, (2) atomic aggregate token reservation across parallel
  specialists, (3) reconciliation of reported usage and interruption, and
  (4) rejection of missing usage.
- **Depends on:** nothing. **Model budget:** not required (contract + proof).

### B2 — Pinned llama-server token-work bound is unproven

- **State:** `src/metis/core/llama_server_backend.py:89` `hard_cap_capable = False`;
  `src/metis/evaluation/llama_cli_cap_probe.py:161` `strict_cap_ready: False`.
- **Evidence:** `docs/studies/issue8-llama-server-work-bound-audit.md` — the
  `4096 + n_predict` reservation is not a proven cap: failed decode/retry work
  is absent from the successful completion's usage fields
  (`server-task.cpp:340-341`), and startup is not shown to make zero
  inference-token calls.
- **Clearing condition (the audit's stated next step):** instrument every
  `llama_process` / encode / decode in the pinned binary and falsify a
  source-derived upper bound under context-edge prompts, forced memory
  failures, timeouts, cancellation, and concurrent callers; prove zero-inference
  startup with `--no-warmup`.
- **Existing assets:** prototype patches `docs/studies/issue8-llama-work-budget-prototype.patch`
  and `issue8-llama-work-receipt-prototype.patch` are preserved in `main` but
  are not integrated or verified.
- **Depends on:** nothing. **Model budget:** not required (local build +
  instrumentation; compute only).

### B3 — Concurrency safety is not established

- **State:** the adapter launches `--parallel 1`;
  `src/metis/core/llama_server_backend.py:86` keeps `hard_cap_capable=False`
  "until integrated concurrency evidence exists".
- **Evidence:** `docs/reports/issue8-concurrent-client-probe-2026-11-21.md`
  exercised only a start-barrier at the cap, not overlapping server-side work.
- **Clearing condition:** evidence of overlapping multi-client work under the
  cap. **Depends on:** B2. **Model budget:** not required.

### B4 — No independent oracle / registered protocol for the next comparison

- **State / evidence:** `docs/studies/issue8-token-capability.md` — "A new
  protocol must be registered before any new comparison calls." Prior studies
  used no real reviewer key or signed controls; the signed-control gate
  authenticates a declaration but does not establish evidence truth, official
  verdicts, or external timestamping.
- **Clearing condition:** register a held-out protocol with an independent
  oracle before any comparison calls.
- **Depends on:** B1–B3 being credible enough to bound pre-call work.
  **Model budget:** not required (design + registration).

### B5 — No qualifying end-to-end comparison has been run

- **State:** the decision-supporting trials (baseline vs a small set of
  alternatives, counting verified solves) have not been run; the earlier 8-run
  comparison exceeded its token budget in 8/8 runs and produced 0 candidates.
- **Clearing condition:** with B1–B4 satisfied, run the comparison within the
  budget and count verified solves only; keep failures and resource use.
- **Depends on:** B1, B2, B3, B4. **Model budget:** **required.**

## Dependency chain

```
B1 (runner cap) ┐
B2 (llama bound)├─→ B3 (concurrency) ─→ B4 (oracle/protocol) ─→ B5 (run = needs budget)
                ┘
Issue #6 single-vs-multi result ─────────────────────────────→ feeds one dimension of #8
```

The current hard stop is B1/B2: the hard cap is not yet provable, so
`strict_cap_ready` / `hard_cap_capable` stay false and B4/B5 cannot proceed.
This gate is the project's own, recorded in the studies cited above.

## Remaining remote branch

`origin/codex/issue8-conservative-bound` (tip `c04fa18`, not an ancestor of
`main`) carries an early version of `llama_server_backend.py` (+276) and
`llama_specialist.py` (+112) with tests and an audit memo
(`issue8-llama-hard-cap-audit-2026-11-19.md`). Those modules already exist in
`main`; the branch does **not** instrument `llama_process` or falsify a bound,
so it does not advance B2. It reads as superseded early foundation, not new
blocker-clearing work. It is retained pending a separate keep/delete decision.

## Budget-zero next steps

1. **B4:** fix the pre-registration requirements for the independent oracle and
   protocol (what must be registered before any call).
2. **B2:** preregister an instrumentation plan — which `llama_process` / decode
   paths are measured and at which edge conditions the source-derived bound is
   falsified — local build only, no API budget.
3. **B1:** document the runner contract (the four conditions above) as an
   acceptance gate.

Only B5 (the actual comparison) requires model-use budget.
