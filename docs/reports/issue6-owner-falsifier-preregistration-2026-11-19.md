# Issue #6 owner plus falsifier reconstruction preregistration (2026-11-19)

## Question

Can a sequential owner plus fresh-context falsifier improve workflow-complete correctness over one owner with the same run-wide call and action caps? This is a new prospective study. The negative symmetric replication and handoff diagnostic remain negative; this protocol does not reuse their tasks or outcomes.

## Frozen treatment and comparator

- Runtime: Codex CLI `0.169.0`, `gpt-6.1-sol`, reasoning effort `low`, memory retrieval disabled. Refuse execution on CLI mismatch.
- Thirty new paired clusters, `task-00` through `task-29`, one attempt per arm and cluster. Seed `2026111906`; each cluster uses `make_task(seed + index, size=20)`. Arm order is shuffled per cluster with seed `seed XOR 0x6A09E667`.
- Each task has 20 shuffled symbols and directed precedence constraints. A hidden seeded permutation generates a chain that gives a unique valid order, plus randomly sampled redundant forward edges. The model sees only the shuffled symbol list and edge list. This is a harder reconstruction task than the earlier two-encoding diagnostic, but it remains synthetic and does not establish CTF or AlpacaHack performance.
- `single`: one owner receives the task and may check and revise its answer within a 14-call, nine-action, 600-second shared run cap. Its assignment max-turn setting is 12; extra calls can service corrections.
- `owner_falsifier`: an owner first produces a provisional private JSON ordering under the same run caps and a six-turn assignment setting. A fresh-context specialist then receives only the public constraints and provisional ordering, with a three-turn assignment setting. It searches for one specific missing, duplicate, unknown, or violated precedence witness and has no oracle. The controller validates the claimed witness against the public artifact and provisional order. Only a valid witness and completed checker wave permit a repair wave with a three-turn assignment setting. Invalid or absent witnesses do not trigger repair.
- Both arms use one active slot, the same Codex model and METIS intent controls, the same candidate/report channel, and the same controller finalizer. The controller compares the final private ordering with the protected seeded order only after all required stages complete; incomplete, timed-out, invalid, or failed workflows score zero in both protected-answer and public-constraint fields. A valid public constraint witness is a repair trigger, not an official or protected-oracle verdict.
- The checker may see the provisional answer in its bounded prompt. It never sees the hidden order, oracle result, or other arm. No model may write a final answer into a report. Candidate stores are purged after each arm.

## Outcomes and analysis locked before model use

Primary outcome is workflow-complete oracle-verified reconstruction. Primary contrast is `owner_falsifier` minus `single` on the 30 paired clusters. Analyze with 10,000 bootstrap resamples of task IDs, deterministic seed `2026111906`; a measured gain requires the two-sided percentile 95% interval to lie entirely above zero. Also report paired discordance, protected-answer correctness after full workflow completion, public-constraint validity after full workflow completion, valid witness rate, attempted repair rate, workflow completion, reserved/observed calls, elapsed time, and token usage as reported turns over total turns. Faster failure is not a gain. No outcome-based task extension, prompt change, or arm exclusion is allowed.

A positive result supports only a narrow claim on this seeded reconstruction family and requires independent held-out replication before closing Issue #6. A null or negative result leaves its measured-gain gate open. The owner/falsifier design is distinct from two concurrent solvers and does not revise previous evidence.

## Retention and stop rules

The runner requires explicit `--execute`; review and commit this preregistration and code before using it. A private, mode-0700 checkpoint outside the repository retains the SQLite audit, temporary artifacts, and an answer-free manifest. The repository output retains only answer-free per-arm booleans, counts, timing, and runtime identifiers. It must not retain symbol orders, candidate bodies, witness contents, hidden answers, raw model messages, or oracle contents. Before starting a new arm, the runner verifies the frozen trial order, retained output, completed-run job states, and reserved call counts against the private scheduler. A completed prefix can resume; an interrupted active arm or any accounting mismatch halts for manual audit without a new model call. Checkpoint state is intentionally retained after completion or abort for audit. No external challenge or service is contacted. Review and execution are separate gates; this commit does not authorize a real-model run.
