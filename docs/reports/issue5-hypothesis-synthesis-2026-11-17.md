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
normalization; paraphrases and punctuation variants can remain separate, and
this does not detect semantic stuckness or equivalent repeated actions.

## Validation

```text
.venv/bin/pytest -ra tests/test_ctf_orchestration.py tests/test_agent_orchestration.py tests/test_agent_autopilot.py
32 passed in 1.97s
.venv/bin/ruff check src/metis/core/ctf_orchestration.py tests/test_ctf_orchestration.py
All checks passed!
.venv/bin/mypy src/metis
Success: no issues found in 52 source files
.venv/bin/pytest -ra
446 passed, 24 skipped in 60.57s
```

The full-suite skips require Linux namespaces/seccomp, browser installation,
external KSNCTF distributions, slow-search opt-in, or a sandbox image. Separately
the sandbox workflow integration passed with its immutable image explicitly
configured.

An independent read-only code review found no blocker for the stated grouping
and scoring behavior. It confirmed the above limits: the score is not
probabilistic, and exact normalized text is not semantic equivalence.

## Remaining gate

This increment improves evidence bookkeeping but does not implement
contradiction resolution, stuckness detection, semantic repeat detection, a
diverse held-out benchmark, or a controlled real-model comparison against a
baseline. Keep Issue #5 open.
