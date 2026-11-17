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
normalization; paraphrases and punctuation variants can remain separate. A
separate stuckness signal now detects the same normalized next action and
hypothesis with an unchanged report status across multiple waves. A retest with
a different hypothesis or outcome remains visible as a repeated action without
being called stuck. Reusing the exact normalized wave rationale is rejected.
This does not detect semantic equivalence between paraphrases.

## Validation

```text
.venv/bin/pytest -q tests/test_ctf_orchestration.py
7 passed
.venv/bin/ruff check src/metis/core/ctf_orchestration.py tests/test_ctf_orchestration.py
All checks passed!
.venv/bin/mypy src/metis
Success: no issues found in 52 source files
```

The full-suite skips require Linux namespaces/seccomp, browser installation,
external KSNCTF distributions, slow-search opt-in, or a sandbox image.

An independent read-only code review of the earlier scoring change found no
blocker for its grouping and score behavior. The current deterministic tests
cover the added cross-wave stuckness condition and exact reason reuse.

## Remaining gate

This increment improves evidence bookkeeping but does not implement
contradiction resolution, semantic repeat detection, a diverse held-out
benchmark, or a controlled real-model comparison against a baseline. The
stuckness signal does not choose an alternate strategy itself. Keep Issue #5
open.
