# Issue #8: bind frozen MUNIN cards to the study protocol

The held-out protocol from PR #54 fixed task artifacts, arm labels and budgets,
but its commitment omitted the MUNIN card set. PR #55 freezes selected cards
per run. This follow-up binds the exact card digests to the protocol hash and
requires finalization to verify each run's treatment against the controller DB.
For a real-model `full` versus `without_memory` comparison, at least one prior
card digest must be declared. Memory-enabled arms must have exactly those
snapshots; the without-memory arm must have none. Each copied payload must
match its SHA-256 and a practice/competition source card created before the
held-out run. A missing table, missing card, extra card, wrong arm, changed
payload or late source is rejected. This is an evidence check, not proof that
the declared arm settings were applied to model calls; the experiment runner
and reviewer must still check that.

An isolated synthetic Rev practice run was created before held-out analysis:
run `4446f379e2ec487bb391775955622906` finished `solved` through a
pre-existing local SHA-256 commitment. Its abstract MUNIN card has digest
`835c160eaeea4845143a21958b78a6f74057fd6d0ac3b643cb8f8a05d474633e`.
The practice run was performed by Daybreak on a generated checker, not by an
autonomous specialist and not on an official CTF. The isolated DB and detailed
answer-free preflight are in `/private/tmp/metis-issue8-benchmark-20261119/`.
The `mr-rabbit` AlpacaHack account showed enabled submission controls for the
candidate `read-a-binary` and `misdirection` pages. Both distributions were
downloaded but not executed or analyzed. No held-out model call, official
candidate submission or benchmark result exists yet. The two tasks were
released in February 2026; prior model exposure remains unknown.

Validation on Python 3.12:

```text
PYTHONPATH=src .../pytest -q tests/test_heldout_study_export.py tests/test_heldout_analysis.py tests/test_heldout_export.py
50 passed
.../ruff check src/metis/evaluation/heldout_protocol.py tests/test_heldout_study_export.py
All checks passed!
.../mypy src/metis/evaluation/heldout_protocol.py
Success: no issues found in 1 source file
```

This branch depends on PR #54's protocol and PR #55's snapshot table. The
experiment remains in preparation; Issue #8 stays open.
