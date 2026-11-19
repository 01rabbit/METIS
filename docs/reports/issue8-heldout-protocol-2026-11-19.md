# Issue #8: prospective held-out protocol and evidence reconciliation

`python -m metis.evaluation.heldout_protocol prepare PROTOCOL.json` validates
a prospective comparison and prints its canonical SHA-256 and deterministic
task/repetition/arm schedule. The protocol fixes task strata and exposure,
distribution hashes, model and runtime pins, arm settings and prompt hashes,
equal budgets, repetitions, and bootstrap seed. The planned matrix is capped
at 2,000 slots. This command performs no model calls or network requests.
For a real-model study, the aggregate declared cap across all slots is at most
50 model calls and 7,200 seconds; finalization also rejects observed aggregate
use above those limits. These limits implement the session's experiment budget
without treating missing provider cost as zero.

After runs, `finalize PROTOCOL.json BINDINGS.json --database STATE.sqlite
--expected-sha256 DIGEST` accepts only bindings with the same protocol hash
and planned slot order. It uses the merged controller-derived exporter and
analysis to validate each run's ledger chain, split, model pin, verifier event,
assignment/report completion, and measured resources. Output contains an
answer-free study, analysis, and ledger reconciliation; a malformed or changed
input fails with a generic error. Run IDs are assigned after preparation, so
this is an evidence pipeline, not a model executor or proof that the study was
registered before any model call. A reviewer must check when the protocol hash
was committed and whether the declared source, arm settings, runtime pin,
exposure, and solvability controls match actual operation. The schedule fixes
the binding order, not independently observed execution chronology.

Local synthetic tests covered successful preparation/finalization, protocol
mutation, distribution hash mutation, mislabeled ablation, declared and
observed call-cap violations, reordered or missing bindings, corrupt ledger
chain, and CLI error suppression. No actual
held-out CTF run, official verdict, cost attestation, or measured ablation was
performed. Issue #8 remains open.

Validation on Python 3.12 with deterministic synthetic SQLite fixtures:

```text
PYTHONPATH=src /Users/mao/Developer/GitHub/METIS/.venv/bin/python -m pytest -ra tests/test_heldout_study_export.py tests/test_heldout_analysis.py tests/test_heldout_export.py
49 passed in 2.04s
/Users/mao/Developer/GitHub/METIS/.venv/bin/ruff check src/metis/evaluation/heldout_protocol.py tests/test_heldout_study_export.py
All checks passed!
/Users/mao/Developer/GitHub/METIS/.venv/bin/mypy src/metis/evaluation/heldout_protocol.py
Success: no issues found in 1 source file
PYTHONPATH=src /Users/mao/Developer/GitHub/METIS/.venv/bin/python scripts/check_repo.py
{"status": "passed", "findings": 0}
git diff --check
passed
```
