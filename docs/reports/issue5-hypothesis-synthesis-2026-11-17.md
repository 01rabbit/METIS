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
request shape, supported tool, option names and assignment artifact scope, then
derives its canonical identity. For stuckness, the controller uses that
identity only when the report also cites an observation sequence recorded for
the same identity in `agent_actions`. A proposal hash alone cannot establish
that the action ran. This catches equivalent single-tool requests with
different wording or normalized inputs (for example, hex strings with
different whitespace). Free-text-only reports retain the exact normalized
text fallback. The signal is advisory and permits a justified retest when
newer evidence is cited. Changing strategy in the current wave clears the
signal; older repeated actions remain visible as history. Reusing the exact
normalized wave rationale is rejected.

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

## Evidence-grounding follow-up (2026-11-17)

The structured proposal's canonical identity is now kept separately from its
evidence-grounded identity. A report gets the latter only if one of its cited
event sequences matches a controller-recorded action row for that identity.
Legacy rows with only the proposal identity do not participate in stuckness
matching. Regressions execute the same canonical hex action across waves with
different wording, check a materially different payload and changed-status
controls, and confirm an unexecuted proposal cannot create a match.

```text
.venv/bin/python -m pytest -o addopts= -q tests/test_runner.py tests/test_ctf_orchestration.py tests/test_codex_specialist.py
66 passed, 2 skipped in 4.25s
.venv/bin/ruff check src/metis/core/models.py src/metis/core/runner.py src/metis/core/fixtures.py src/metis/core/ctf_orchestration.py tests/test_runner.py tests/test_ctf_orchestration.py tests/test_codex_specialist.py
All checks passed!
.venv/bin/mypy src/metis
Success: no issues found in 52 source files
```

The two skips are the optional Docker-backed cases; this focused run validates
the local controller and fixture path, not container execution.

An independent review found no blocker in the evidence binding or controls. It
confirmed the scope is limited to canonical single-tool identity cited through
controller observations; exact-normalized hypothesis grouping can still miss
paraphrased hypotheses, and multi-step strategy equivalence remains outside
this signal.

An independent read-only code review of the earlier scoring change found no
blocker for its grouping and score behavior. The current deterministic tests
cover the added cross-wave stuckness condition, clearing after a strategy
change, and exact reason reuse.

## Remaining gate

This increment detects canonical equivalence only for an explicitly structured
single-tool proposal whose matching execution is cited; it does not infer intent
from paraphrased prose or detect multi-step strategy equivalence. It does not
implement contradiction resolution, a diverse held-out benchmark, or a
controlled real-model comparison against a baseline. The stuckness signal does
not choose an alternate strategy itself. Keep Issue #5 open pending review of
its complete acceptance gate.
