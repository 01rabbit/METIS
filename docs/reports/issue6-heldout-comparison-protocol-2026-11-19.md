# Issue #6 proposed held-out comparison

The [action-reserved conditional pilot](issue6-conditional-reserve-pilot-results-2026-11-18.md) scored 11/12 compared with 12/12 for single and reached its stop condition. That registered policy ends there. This proposal compares an explicitly different policy, complementary independent analyses joined by a blinded finalizer, with a fresh ordinary single attempt and two independently sampled single attempts. A model trial requires a separately frozen registration and runtime verification.

## Tasks and blinding

Use self-contained, benign offline data-reconstruction puzzles. Draw 60 previously unseen instances, 20 per family, from three public specifications. Each family has a deterministic curator-side validator and combines three or more interacting stages.

- Reconstruct records from synthetic log fragments after resolving clock offsets, aliases and missing or duplicated events.
- Recover an original table from interleaved byte records using public format rules, checksums and ordering constraints.
- Infer a consistent assignment from synthetic scheduling constraints with redundant and conflicting evidence.

Pilot task generation, uniqueness checks and I/O on separate development instances. Reject an ambiguous, malformed or duplicate instance before registration. Freeze the family counts, generators and answer format, then draw fresh private seeds. A curator generates the full held-out bundle, validates the unique target assignments, and freezes each public payload and its task ID in a hashed manifest. Record a private keyed commitment to the answer set and retain the key separately. Use an independently timestamped registration and retain the sealed bundle and private oracle for authorized replication. Treat every task as one paired cluster. Retain every frozen task once the first arm starts.

All arms receive byte-identical task inputs and the same artifact interface. Restrict the task environment to provided files and deterministic, network-free computation. Keep the private oracle in a separate controller boundary. The model, selector and worker sessions cannot access the answer set, its seeds, the sealing key, another arm's outputs, or oracle results. The evaluator accepts only one finalized answer per arm after all execution and selection ends. Test these boundaries with artificial answers before registering the real bundle.

## Arms and resource accounting

| Arm | Workers | Common finalizer |
| --- | --- | --- |
| Single | One worker with the whole worker allocation | Evaluates its anonymous submission |
| Single best-of-two | Two fresh workers with the same generalist instructions, each with half of the worker allocation | Evaluates both anonymous submissions |
| Complementary | Two fresh workers with separate evidence-reconstruction and constraint-checking instructions, each with half of the worker allocation | Evaluates both anonymous submissions |

Freeze the model, provider, runtime version, exact candidate and work-product schemas, role instructions and common finalizer prompt. Use the same finalizer rules in every arm. The permitted response forms are selection of a complete candidate or construction of a final answer from the submitted evidence. Apply the same parser and normalization to the final response in all arms. A fresh common finalizer is charged even in the single arm. Never select by oracle correctness. The two multi-worker arms can use identical slot and candidate-order policies. Randomize arm order and slot order with public independent seeds, and reset context, working directory and model history between each arm.

Set a single total budget per case-arm for worker and finalizer combined. Freeze the exact integers at registration following development-only checks. Reserve model calls, input and generated tokens including reasoning, mediated actions, and wall time before dispatch. Both two-worker arms have identical worker suballocations. All arms reserve the same finalizer suballocation. Global slots have the same maximum and remain idle when an arm has fewer workers. Count retries and invalid responses in spent resources. Missing provider usage, tool bypass, incorrect pinned settings or an inability to enforce a registered resource cap invalidates execution. Retain completed records and the failure state. Do not infer equal token exposure from a call limit or post-hoc usage. Execute no held-out model calls until budget probes demonstrate reservation, rejection at each cap, cancellation, and response attribution for the exact runner and model.

## Scoring and inference

Workflow success requires the required worker slots to terminate within the registered contract, one finalized answer in the shared format, and a true oracle verdict. A worker may complete by returning a valid explicit abstention. Provider or controller failures that compromise a common prerequisite invalidate the study; ordinary exhaustion, invalid outputs, and unsuccessful answers score zero. Record completion, verifier outcomes, resource usage, and paired successes separately. Export only enumerated states, opaque task IDs, and resource counters.

The primary contrast is complementary minus single best-of-two paired workflow-success rate. The complementary-minus-single contrast is a co-gate. Use an exact one-sided McNemar test for each at alpha 0.025, with positive measured differences of at least 10 percentage points in both comparisons. Report both contrasts, discordances, and missing or invalid execution separately. Use no interim tests, task replacement or tuning. A new analysis is exploratory if it changes the denominator or endpoint after registration. Reproducibility needs a second precommitted fresh bundle under the same protocol, with both comparisons passing separately.

The [offline scorer](../../src/metis/evaluation/issue6_heldout_comparison.py) independently checks the registered task IDs and family counts, complete pairing, answer-free schemas, and reported usage against the declared caps. It computes the two exact tests for one bundle. Run the scorer from an environment with METIS installed.

```sh
python -m metis.evaluation.issue6_heldout_comparison registration.json outcomes.json
```

The scoring registration contains `commitment`, `tasks` (`id`, `family`), and `cap`. The outcome export contains the matching `commitment` and `records` (`task`, `arm`, `outcome`, `oracle_verified`, `usage`). Keep the canonical registration manifest and its timestamp evidence separate from this scoring view. The scorer compares the supplied registration commitments and reported counters. Independent audit must establish provenance, exact runtime settings, and actual enforcement. The study still needs a held-out generator, isolated runner, frozen registration, budget attestation, and both real trial bundles.

The separate `issue6_cohort_audit` command wraps these same two schemas and
requires canonical export serialization in registration task order and the
scorer's fixed arm order. This checks packet consistency only; it does not
establish actual execution order. The current registration and outcome
schemas contain no per-run execution receipts, runtime/configuration digests,
start/finish/deadline values, or authenticated evidence references. The audit
therefore marks those evidence classes unavailable and never returns a
qualified or verified cohort. Caller-added receipt fields are rejected by the
strict existing trial schema. A `consistency_only` result is not evidence of
execution, provider-limit enforcement, or measured gain.
The command reads at most 1 MiB from each input file and suppresses file and
validation details on failure.

```sh
python -m metis.evaluation.issue6_cohort_audit registration.json outcomes.json
```
