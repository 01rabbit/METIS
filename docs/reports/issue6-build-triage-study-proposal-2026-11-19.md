# Proposed Issue #6 build-triage reviewer study

This proposal contains a fixture generator and an independent correctness check.
It has no real-model results. Freeze the implementation and protocol after the
checks below and before any model is called.

## Question and workflows

Does a reviewer with a fresh context improve root-cause localization over
review by the same specialist, when both see the same public evidence and can
revise their candidate under the same resource limits? The previous symmetric
replication and handoff diagnostic remain negative. The owner/falsifier study
scored 30/30 in both arms and exercised no witness-triggered repair. It therefore
left this question unanswered.

Use one active specialist slot. Each arm has an owner phase and a review phase.

| Phase | Single specialist | Owner plus reviewer |
|---|---|---|
| Initial diagnosis | The owner receives the runbook, build DAG, allowed causes, and partial log | The owner receives the identical inputs and instruction |
| Review and final diagnosis | The owner sees the public input, its provisional proposal, and its own bounded work note | A fresh specialist sees the same public input and provisional proposal |
| Scoring | Daybreak checks the final structured proposal once against the protected verifier | Daybreak uses the identical validator and scoring rule |

Use the same diagnosis instruction and the same instruction to check and, if
needed, revise the diagnosis. Pass the same model and reasoning settings to
both phases in both arms. Give both arms the same two per-phase hard call
limits, private candidates/actions, completion criteria, prompt window, provider
token limits if enforceable, monotonic deadline, and finalization path. Proposed
limits are one model call and one combined candidate/report action per phase,
60 seconds per phase including setup and finalization, and no retries. The
provider's observed token use is diagnostic. An arm-level hard token ceiling may
be advertised only after it is proved enforceable before and during calls.
Before execution freeze actual model/runtime identifiers, exact decoded input
and output caps enforceable by the selected backend, and tokenizer and settings
pins. Stop at preflight if the selected backend cannot enforce the registered
limits. Freeze charge semantics for failed launches and missing usage; record
charges from the actual ledger.

Use a preloaded public artifact and enforce the structured diagnosis schema
before the first call. Stage one also returns a bounded private work note in
both arms. This note is visible to the owner reviewing its answer and is
excluded from the fresh reviewer's context. Its schema, byte cap, and lifetime
are identical in both arms. No system-validated witness or correctness feedback,
including the oracle's candidate enumeration, may enter either model context.
Both reviewers must emit a final complete option, even when the provisional
answer is correct. If the initial call or handoff fails, score zero without an
oracle check. A failed, malformed, or late final submission also scores zero.
An audit, isolation, accounting or fixture-disagreement failure halts execution
and preserves answer-free evidence. Freeze handling of partial execution before
starting, with no outcome-based repeats or exclusions.

The existing bounded Codex assignment helper has a new in-memory transcript
for every invocation. Running two ordinary waves in both arms would not by
itself demonstrate owner continuity. Preflight must prove the explicit private
owner-note handoff and the independent reviewer context through the actual
METIS scheduler, and reconcile intended source fields with a prompt receipt.
The planned intervention is the owner-note handoff. The scope of the claim is
the resulting two-phase workflow; it does not establish parallel-search or
general CTF gains.

## Public distribution and oracle

A fixture simulates a build DAG with two worker pools. One job runs slowly, one
dependency artifact becomes available late, or one pool temporarily loses a
worker. The public rules state dispatch priority, event timing, and loss
behavior. Partial event records resemble a log excerpt and require correlating
dependency readiness with worker occupancy. A reviewer may check any cause
against the full public input. Neither workflow receives a privileged shard.
Balance the three latent families by fixed index before fixture generation,
and never expose the balanced family index to a solver.

`issue6_build_generator` generates events by advancing to completion,
availability and capacity boundaries. The separately implemented
`issue6_build_oracle` enumerates the entire finite cause list with a tick
simulation. It does not receive the injected cause or the generator's full
schedule. A fixture qualifies only if there is exactly one matching cause and
it agrees with the injected cause. Fixed-seed continuation is allowed for
ambiguous or observation-free proposals. Generator/oracle disagreement or
exhaustion halts. Validate known hand schedules independently, including
worker-loss boundaries, delayed artifacts, ambiguity, and mutated observations.

The selected task population is thus uniquely diagnosable under the declared
model. Admission can favor highly diagnostic observations, especially when
worker loss never affects execution. Publish per-tier and per-family
admission aggregates and distinguish this scope from unfiltered real build
failures. With two workers and a small candidate list this remains a finite
simulation task. Its behavior with arbitrary solver tools, incomplete runbooks,
real build logs, or other task families is unmeasured. Both pilot and evaluation
use the same scoped artifact access and no shell execution.

## Calibration and sampling

Before calling a model, commit the pilot seed schedule, fixed family counts,
and selection rule. Use 12 pilot tasks per tier (four per family) for single
specialist only. Use all three tiers in fixed order. Choose the first of
small, medium, and large with 4–9 verified complete outcomes out of 12 and at
least 10 completed workflows. Selection considers no treatment outcomes.
If no tier qualifies, stop and report. A low solve rate produced by orchestration
failure cannot qualify a tier. The pilot is calibration only and all results
are recorded.

After calibration, obtain two independently sampled private seed sets from an
independent custodian. Freeze an opaque commitment, disjointness check, fixed 60
fixture IDs and cause-family schedule (20 each) for each cohort, admitted input
manifest, and paired arm order. Pilot, first cohort, and replication have
disjoint seed sets and public fixture identities, with no duplicate fixture
under a canonical field ordering. The custodian freezes both manifests before
the first cohort's launch. Use no seed substitutions except the generator's
registered admission procedure. Run each pair adjacently, with order balanced
by family and fixed independently of the task generator. Preserve actual
execution order, including failures. Both cohorts use the same chosen tier,
model settings and code, so the second cohort tests independent draws from the
same family. A family-wide claim needs further evidence across task domains.

## Decision and budget

The primary endpoint is workflow-complete, oracle-verified final diagnosis.
Denominator is all admitted, scheduled pairs in a completed cohort. Report the
paired risk difference, all four paired outcome counts and a paired 95%
confidence interval (freeze a paired score interval and implementation before
execution). Exact two-sided McNemar p-value is an independent decision check.
A gain requires a positive difference, a strictly positive lower confidence
bound, and exact p < 0.05 in each cohort. Null, negative, incomplete, or
discordant replication leaves Issue #6 open. Publish raw final correctness
where defined, completion, latency, reserved and actual calls, observed
input/output tokens, and provisional-to-final transitions computed only after
model stages have finished. The common single comparator receives both phases.
A gain can arise from correction, avoiding degradation, or both.

The maximum is 72 pilot calls plus 480 evaluation calls (552 total). At two
minutes per arm, serial model-and-arm hard wall ceilings total 9 h 12 min, of
which 72 minutes is calibration. This excludes setup, independent review and
teardown. Timing from PR #84 (roughly 8.6 seconds per observed call including
workflow operations) would suggest roughly 80 minutes of model/arm time for
552 calls, but is not a forecast for a new backend and harder tasks. Use the
pilot's wall-time measurement and reserve time for post-run audit. If the
remaining window cannot accommodate the registered execution and audit, disclose
that the evidence will be late. A late result must use the frozen design.
Sixty pairs per cohort can detect large, reasonably one-sided shifts and can
miss modest gains. Treat the two-cohort requirement as a narrow replication
gate and report the observed interval even on failure.

## Retention

Publish protocol hash, runtime pins, opaque case labels, admission/call/usage
counts, observed timings, completion and verification booleans, paired analysis,
and sanitized failure classes. Keep oracle and solver contexts on a private
ephemeral root with restricted access. Do not retain exact seeds, per-case
latent families, candidate values, work notes, full prompts, or oracle outputs
containing cause values in study artifacts. The public fixture is necessarily
sufficient to compute the answer, so keep the actual evaluated fixture inputs
out of public results. Allow independent audit before ephemeral cleanup via a
custodian-held sealed copy if authorized by the execution plan; freeze its
expiry before launch. Public example fixtures use unused seeds and support
deterministic testing of semantics rather than disclosure of evaluation cases.
Reconcile actual runtime receipts, per-stage budget, oracle calls, finalization,
and cleanup before releasing results.
