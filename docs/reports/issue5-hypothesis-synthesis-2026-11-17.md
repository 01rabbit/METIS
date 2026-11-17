# Issue #5: hypothesis-level synthesis scoring (2026-11-17)

## Change

`AgentLedger.synthesize` now groups reports by hypothesis text after case-folding
and collapsing whitespace. For each group it emits support, rejection, and
inconclusive counts, a simple integer score (`supported - rejected`), and the
referenced event sequence set. A contradiction is reported only when the same
normalized hypothesis has both a supported and a rejected report. A rejected
report about a separate hypothesis no longer contradicts every supported
hypothesis in the wave.

The score is a report-count difference, not a calibrated confidence or an
independence-weighted evidence measure. Grouping is exact text after minimal
normalization; paraphrased hypotheses remain separate. A stuckness signal
detects the same action and hypothesis with one unchanged status across
adjacent waves. New reports can include a structured `next_action_intent`
declaring a bounded future METIS tool request; the controller validates its
tool, options and assignment artifact scope, then derives its canonical
identity. This catches equivalent single-tool requests with different wording
or normalized inputs (for example, hex strings with different whitespace).
Free-text-only reports retain the exact normalized text fallback. The signal is
advisory and permits a justified retest when newer evidence is cited. Changing
strategy in the current wave clears the signal; older repeated actions remain
visible as history. Reusing the exact normalized wave rationale is rejected.

## Validation

```text
.venv/bin/pytest -q tests/test_ctf_orchestration.py tests/test_codex_specialist.py
38 passed in 3.55s
.venv/bin/ruff check src/metis/core/agent_contracts.py src/metis/core/ctf_orchestration.py src/metis/core/codex_specialist.py tests/test_ctf_orchestration.py tests/test_codex_specialist.py
All checks passed!
.venv/bin/mypy src/metis
Success: no issues found in 52 source files
.venv/bin/pytest -ra
473 passed, 29 skipped in 68.12s
.venv/bin/ruff check src tests
All checks passed!
```

The 29 full-suite skips require Linux namespaces/seccomp, browser installation,
external KSNCTF distributions, slow-search opt-in, or a sandbox image.

An independent read-only code review of the earlier scoring change found no
blocker for its grouping and score behavior. The current deterministic tests
cover the added cross-wave stuckness condition, clearing after a strategy
change, and exact reason reuse.

## Remaining gate

This increment detects canonical equivalence only for an explicitly structured
single-tool proposal; it does not infer intent from paraphrased prose or detect
multi-step strategy equivalence. It does not implement contradiction resolution,
a diverse held-out benchmark, or a controlled real-model comparison against a
baseline. The stuckness signal does not choose an alternate strategy itself.
Keep Issue #5 open.
