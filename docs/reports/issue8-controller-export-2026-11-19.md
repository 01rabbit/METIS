# Issue #8: controller-derived, answer-free trial export

`python -m metis.evaluation.heldout_study_export MANIFEST.json --database STATE.sqlite`
now assembles a `heldout_analysis.Study` JSON record from an existing METIS
database without creating tables. It complements the retained single-run
`heldout_export.snapshot_run` interface. The caller supplies a complete study
manifest: task labels, exposure/solvability declarations, equal arm budgets,
and one run ID per task, repetition and arm. Missing or repeated cells fail.

The exporter validates each run's full event hash chain and split, then derives
the terminal verifier class, assignment/report completion, charged actions, reserved model
calls, elapsed event time, and available job token usage. A real-model study
must match the declared model to every assigned job. It never copies event
details, candidates, answer values, artifact paths, or raw model messages.
Provider dollar cost remains `null`. Token totals are exported as reported
Codex CLI usage only when every charged scheduler reservation joins exactly one
retained CLI turn event for its current, unsuperseded attempt. The job aggregate
must identify `codex-exec`, cover exactly that many turns, and have positive
integer input and output counts. Runs with no charges, missing or legacy
coverage, ambiguous or oversized usage, and retried jobs leave the run total
`null`. The charged reservation count remains in `model_calls`. It counts
scheduler reservations. CLI aggregate coverage does not authenticate individual
token measurements, count provider requests, or demonstrate an enforced cap. The existing analyzer excludes these rows from resource-complete P7
acceptance scoring. Task exposure, protected-oracle truth, solvability controls,
and runtime pin remain declarations for independent review, not attestations.

Deterministic synthetic tests cover valid export and ledger reconciliation,
corrupt event-chain rejection, split and incomplete-matrix rejection, missing
usage, and model-pin mismatch. No real model, external CTF, or official
submission was used. This is an evaluation-data component; it does not meet
Issue #8's held-out repeated benchmark gate.
