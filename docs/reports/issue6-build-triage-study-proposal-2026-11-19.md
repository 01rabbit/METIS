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
limits, private candidates/actions, completion criteria, prompt window and
monotonic deadline. Proposed limits are one model call and one combined
candidate/report action per phase, 60 seconds per phase including setup and
finalization, and no retries. CodexCLI is eligible for this synthetic Issue #6
comparison if the runner enforces those limits and proves matched settings
before the pilot. Report observed provider usage and missing usage; this
design does not claim a hard provider token ceiling. The hard-token and
trial-admission requirements for real held-out CTF studies such as Issue #8
are separate. Freeze the actual model/runtime pins, prompt size and output
schema, and charge semantics for failed launches and missing usage. Record
charges from the actual ledger.

Use a preloaded public artifact and enforce the structured diagnosis schema
before the first call. The proposal contains one string-valued opaque option ID and no extra fields.
Stage one also returns a bounded private work note in
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
worker-loss boundaries, delayed artifacts, ambiguity, and mutated observations. Send only the canonical fixture artifact to either
workflow. Its normalized hash is used for deduplication, while solver inputs
omit the seed, latent family, identity label and admission counters.

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

If the runner preflight and calibration qualify, prepare a fresh disjoint
60-pair evaluation cohort with 20 per cause family. Freeze the seed-set
commitment, case IDs, family schedule, canonical fixture manifest,
analysis code and randomized arm order before the first model call in that
cohort. Check pilot/evaluation disjointness by seed and canonical fixture
identity. A delegate independent of execution can inspect the frozen
commitment. Use no seed substitutions except the registered admission
procedure. Run paired arms adjacently, with order balanced by family and
fixed independently of generation. Preserve actual execution order including
failures. A positive primary result permits a separately committed fresh
replication under the same frozen settings if time allows. An independent
replication is required before counting the result as Issue #6 acceptance.
A family-wide claim needs further evidence across task domains.

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

The proposed calibration is up to 36 arms and 72 calls, with a 72-minute
serial hard wall cap. Launch calibration only after symmetric runner
preflight. A subsequent one-cohort comparison is 120 arms and at most 240
calls, with a four-hour serial hard wall cap. These stages exclude setup
and audit. Use the pilot's measured wall time to assess whether the first
cohort and audit fit. If not, report calibration and keep the gate open.
Replication is separately scheduled and budgeted only after a positive first
cohort. Sixty pairs can identify large, reasonably one-sided shifts and can
miss modest gains. Report the interval even when a cohort fails the gate.

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
