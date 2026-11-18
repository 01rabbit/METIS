# METIS implementation status

## Codex-native solve workflow

The active implementation is on `metis-full-implementation`. Codex supplies the
reasoning, so this workflow has no model API key or Docker prerequisite.

Implemented:

- Authorized URL intake for generic HTML and CTFd, scoped redirects and
  downloads, bounded response sizes, DNS rebinding checks, proxy/TLS support,
  private cookies, and optional token/cookie authentication.
- Private local challenge sessions with action/time budgets, file snapshots,
  exact artifact scope, recovery, cancellation, and a run board.
- Thirty-seven bounded data/crypto helpers and twenty-six static artifact
  analyses spanning common crypto, web, forensics, reverse engineering, pwn
  preparation, and misc formats.
- Official CTFd answer verification and fail-closed generic HTML form
  verification. HTTP 200, reflected candidates, and local regex extraction are
  not accepted as proof.
- Duplicate rejection, submission caps, rate-limit handling, and a required
  post-feedback hypothesis revision before a new candidate after an incorrect
  verdict.
- MUNIN technique cards with evidence/run provenance, successful-solve gating,
  failure-evidence gating, held-out exclusion, secret/flag guards, search, and
  split-aware retrieval during later intake and specialist briefs. Existing
  sessions migrate to `unlisted` and receive no cards; retrieval can be disabled
  for ablation.
- A project-local setup script, six synthetic category exercises, and a local
  CTFd-shaped rehearsal server.
  The 2026-11-17 focused category/orchestration run passed 22 tests across
  `tests/test_codex_practice_categories.py`, `tests/test_agent_orchestration.py`,
  and `tests/test_ctf_orchestration.py`; see
  [`p2-offline-category-fixtures-2026-11-17.md`](reports/p2-offline-category-fixtures-2026-11-17.md).

- Remote services (`metis remote`): suggestion-only statement parsing, explicit
  per-run TCP/TLS grants, bounded scripted exchanges and solver pipes,
  DNS-rebinding refusal, transcripts saved as scoped artifacts.
- Dynamic sandbox (`metis sandbox`): immutable image, no network, read-only
  root, no host mounts, capability-free unprivileged user, resource limits;
  run/strace/ltrace/gdb/script modes; bundled Dockerfile with pwntools.
- Platforms: rCTF adapter (team-token login, catalog, open, strict `kind`
  verdicts, `timeLeft` cooldown) and optional scoped JavaScript rendering.
- Claude Code: project skill, `/ctf` command, eight category subagents mapped
  to `metis plan` roles, startup prompt via `./start --agent claude`.

## Observed evidence

The local rehearsal exercised the full generic path: URL statement/file
acquisition, decoding, an intentional incorrect official submission, a recorded
revised hypothesis, a corrected verified submission, abstract success/failure
knowledge storage, retrieval on a second challenge, and a first-attempt verified
submission there. Random rehearsal answers were not stored in source or reusable
knowledge. This is integration evidence, not a general solve-rate measurement.

Issue #4 also has a deterministic same-policy retrieval ablation across three
distinct synthetic messages. Retrieved ROT13 knowledge changes candidate
ranking; retrieval-off keeps the generic baseline. All paired outputs passed
the local commitment oracle, with one action versus two per target. This is
policy plumbing evidence, not LLM behavior or a general solve-rate claim; see
`docs/reports/issue4-munin-ablation-2026-11-17.md`.

Issue #5 now has bounded, declarative evidence-conditioned fallback routes:
only a named `invalid_input` parse rejection on the same challenge input can
select a distinct, untried planned tool request; non-text, execution, timeout,
policy, and unknown failures halt. The runtime records the evidence and
rationale before the alternate action. A paired 30-fixture synthetic
comparison used both Base64 and hex first-action orders under equal
three-decision/time limits. It scored
30/30 verified solves for the adaptive policy and 16/30 for the fixed
first-action baseline, with paired bootstrap 95% interval [0.300, 0.633] for
the solve-rate difference. The mock runtime now distinguishes parser rejection
from non-text output consistently with the worker. This remains synthetic
mechanism evidence; broader semantic hypothesis and multi-step strategy
handling, diverse held-out tasks, and real-model comparison remain open. Issue
#5's listed acceptance gate was met and the issue was closed on 2026-11-17
after independent conditional GO and exact-head CI success; the broader P4
roadmap remains open. See
`docs/reports/issue5-adaptive-replanning-2026-11-17.md`.

Final test, lint, type, build, bootstrap, and fresh-clone results for this
increment are recorded in `docs/reports/codex-native.md` after validation.

The 2026-11-12 completion increment is recorded in
`docs/reports/completion-2026-11-12.md`, including a real Docker run of the
sandbox (gdb, strace, script mode, network and filesystem isolation probes) and
a real Chromium rendering check.

The 2026-11-17 AlpacaHack Daily evaluation is recorded in
`docs/reports/alpacahack-evaluation-2026-11-17.md`. Four authorized August
challenges have official browser-observed solves across Rev, Web, Crypto, and
Misc. This demonstrates scoped challenge intake, one-instance remote
workflow, browser submission, official verdict attestation, and category
extraction against live pages. Password, Please was Daybreak-led, and Daybreak
performed the bounded collision search for Happy Birthday. These are not
evidence that an autonomous specialist produced the answers.

The `One More Approval` Daily challenge was additionally used for a local-only
METIS test. Two Codex specialist roles independently identified the
complementary ECDSA `s` transformation, and the supplied source accepted it in
an isolated test using a pure-Python compatibility shim. The configured image
lacks PyCryptodome, so this is not a library-level or official solve; the card's
individual prior-solve state was also not explicit. No submission was made.
Details and limitations are in
[`alpacahack-one-more-approval-local-2026-11-17.md`](reports/alpacahack-one-more-approval-local-2026-11-17.md).

The authenticated Daily attachment for `Long Long Flag Printer 2026` was also
used in a bounded local-only METIS run. Its source hash and artifact provenance
are recorded in
[`alpacahack-long-long-flag-printer-static-eval-2026-11-17.md`](reports/alpacahack-long-long-flag-printer-static-eval-2026-11-17.md).
The `misc-specialist` used read-only artifact intents to establish that the
redacted 1,024-character value is printed in order, with an index-based sleep
after each character; the requested delays sum to 523,776 seconds. No challenge
code ran, no endpoint was granted or contacted, and no answer was submitted.
The local verifier was unavailable because the attachment redacts the value.
One specialist produced an evidence-backed report. The other assignments first
failed closed after attempting a prohibited re-delegation tool; a bounded critic
retry then exhausted the shared model-call cap after repeatedly citing evidence
the controller rejected. Synthesis was ready but incomplete. This is a bounded
real-model static-analysis trace, not a solve or a completed P4/P7 gate. Issue
#5 is closed; Issue #8 remains open.

Separately, Codex CLI 0.169.0 completed one generated local direct-answer fixture
through the `CodexProvider`; the private external fixture oracle independently
verified the candidate. The run observed 6,902 input and 41 output tokens, while
dollar cost was unavailable. A Base64/tool-path attempt failed closed because
the local Docker cgroup configuration could not confirm resource enforcement.
This is one fixture result, not an AlpacaHack solve or a solve-rate benchmark.
Issue #2's acceptance criteria are now covered by the real-model oracle run,
always-run Crypto/Misc deterministic fixture tests, and existing budget/failure
tests. Docker-backed category runs remain skipped on this host because cgroup v2
resource enforcement is unavailable. Other acceptance gates remain open.

After hardware-key reauthentication, the 2026-11-17 KSNCTF #33 offline
regression reached `view` and private candidate handoff without reproducing
the authentication error. A Daybreak metadata audit also checked all four
decrypted server responses without reading their bodies. This satisfied Issue
#24's reauthentication regression condition, and the issue is closed. The
challenge was not submitted to its official verifier; details and limits are in
`docs/reports/issue24-reauth-regression-2026-11-17.md`.

Issue #16 is now closed after Linux real-Codex probes on CLI 0.166.0 and 0.169.0
verified OS isolation and configured spawn refusal without `--ephemeral`; see
`docs/reports/issue16-linux-real-codex-2026-11-17.md`. The refusal depends on
the tested CLI configuration, the tool can remain visible, and Linux was tested
from the VM's root account. Unsupported platforms remain fail closed.

Issue #28 has bounded Biham–Kocher and Info-ZIP seed tools. Its synthetic intent
test covers recovered-key decryption with CRC checks for every member, then XOR,
using a reduced candidate set. A separate opt-in slow test now confirms full
Biham–Kocher candidate search and all-member CRC validation on a synthetic ZIP
(8 workers). Another opt-in slow test covers full search through specialist
intents, decryption and XOR in a combined pair of slow tests (`2 passed in
125.77s`); this is a scripted intent test, not a model-driven solve. The parent
now terminates candidate workers at the wall-clock deadline, with a dedicated
reason-code test (`1 passed in 0.69s`). ZipCrypto attacks now use a fixed
2 GiB/4 CPU no-network container profile with cgroup limit checks and an
end-to-end timeout that kills the entire worker process group. The generic
512 MiB OOM probe and deadline cleanup tests passed; ZipCrypto's OOM reason
mapping has a deterministic unit test. A real-container ZipCrypto route OOM
test passed in CI under a fixed 128 MiB test profile (`5 passed in 76.78s` on
exact head `9465732`). The ZipCrypto worker now emits bounded phase markers for
module imports, worker startup, archive parsing, candidate reduction, and candidate key search;
OOM and timeout results preserve the last observed marker as diagnostic `phase`
while keeping the stable `sandbox-oom`/`sandbox-timeout` stage. A real-container
low-memory test confirms the result carries one of the allowlisted phases. This
best-effort diagnostic attributes the OOM to a coarse worker phase, not a
specific internal loop; an OOM that kills the supervisor may still have no phase.
A new synthetic memory-pressure test in the
actual 2 GiB ZipCrypto profile observed the cgroup OOM marker, mapped it to
`memory_limit_exceeded`, and confirmed worker-registry cleanup. This validates
production-profile OOM classification and cleanup, but does not show a natural
ZipCrypto candidate search reaching the limit. The final listed #28 resource
acceptance item is now met: the real-worker deadline and production-profile
synthetic cgroup OOM tests return bounded reason codes and clean up. All three
listed acceptance checkboxes are checked; the Issue remains open because Stay
key recovery and ksnctf #39 remain unresolved. A bounded upstream reference
probe also compiled temporary CPU-only targets. The original embedded test
run OOMed at both 512 MiB and 2 GiB before producing a stage-one shard. A
compact-bucket Stage 1 prototype completed Stage 1a (84,148,224 candidates)
but OOMed in Stage 1b at 2 GiB before writing a shard. This narrows the next
memory target to Stage 1b's in-memory candidate accumulation. A separate
oracle-assisted `-only_emit_correct` self-test retained exactly one known
candidate, validated its 18-byte shard, and peaked at 1,167,056,896 bytes;
normal attack mode was unchanged and still has no passing resource result.
Neither run is an independent reference vector. One full intent search in the isolated
route recovered keys, checked both members' plaintext and CRC, then decrypted
and XORed (`1 passed in 34.27s`); a different synthetic input exceeded its
300-second budget. Container creation, engine attach, and OOM inspection timeout
results now map to `worker_failed` with their infrastructure phase; only the
in-container supervisor's workload deadline maps to `work_exceeds_budget`.
Timeout/OOM phase attribution now preserves the furthest parent phase when
spawned workers re-emit earlier import markers. AlpacaHack Daily held-out
`zen.zip` known-plaintext runs with 32 and 80 exact public bytes both reached
`candidate-key-search` and exceeded the 300-second tool limit; neither
recovered a key or was submitted. Fake-engine phase tests and
real-container deadline/OOM tests pass. Stay recovery and natural candidate-search OOM
remain unproven. The 2020 two-file attack's paper was reviewed; legacy CPU code
was compiled and attempted only in the bounded temporary probe documented in
`docs/reports/issue28-breakzip-reference-audit-2026-11-17.md`. Docker-backed budget and
full-intent integration checks now run in a dedicated GitHub Actions job.
See `docs/reports/issue28-zipcrypto-2026-11-16.md` and
`docs/reports/issue28-stay-assessment-2026-11-16.md`.

On 2026-11-18 the user directed us to use the official #39 distribution source.
The official page and same-origin PHP source and ZIP were fetched into METIS run
`0045b063168045c289eaef276dab21c2`. The archive's seven members match the
Info-ZIP double-encrypted-header profile; the bounded seed search predicted the
random bytes for every member. This is PRNG/header analysis only: those bytes
are not Biham–Kocher known plaintext for the ZIP data stream; they are the
stream-byte XOR constraints used by Stay section 4. A dummy-key decryption was
rejected by the header check, and no Stay inverse recovery, independent
synthetic Stay vector, or official submission has occurred. Issue #28 and
ksnctf #39 remain open; see `reports/issue28-stay-assessment-2026-11-16.md`
and the live run evidence.

A separate direct bit-vector SMT feasibility probe on two synthetic members
returned `unknown` at a 60-second timeout. This does not test the target or a
tuned solver; it rules out treating a naive full-state encoding as an immediate
replacement for Stay's staged inverse search.

The authenticated AlpacaHack Daily account was rechecked in the browser on
2026-11-18 before a new held-out evaluation. September, October, and November
showed 13/13, 11/11, and 6/6 solved, respectively; future November dates were
still being prepared. The October `fsbase modification` detail had a disabled
solved form. No unsolved Daily item was available, and no server or submission
was initiated in this recheck. This is an availability blocker, not a new
benchmark result; the August solves in the prior evaluation report are not
fresh repeated held-out trials. Issue #8 remains open.

A separate forward-only interoperability check generated a synthetic seven-
member stored archive with Info-ZIP Zip 3.0. METIS matched all known payloads
and CRCs, its header check bytes matched the DOS time fields on all seven
descriptor entries, and independent `unzip -t` passed. This validates normal
ZipCrypto header/decryption behavior only; Stay's inverse key-recovery
recurrence and runtime remain unvalidated. A separate 10,000-state synthetic
test validates the first-byte cancellation and second-byte differential
relation from Stay section 4 against direct two-pass encryption, using an
independent bitwise CRC transition (`1 passed in 0.35s`). It does not validate
the paper's inverse candidate search. A second forward interoperability check
matched the relation on seven Info-ZIP-generated header pairs decrypted with
CPython's independent `zipfile._ZipDecrypter`; METIS CRC checks and external
`unzip -t` passed. A further reduced 12-bit synthetic search matched the
formula's complete candidate survivor set against direct enumeration for five
observations, and a one-byte-corrupted control rejected the planted state.
This does not cover Stay's published 23-bit slices/carry pruning or full-state
recovery. See
`reports/issue28-stay-assessment-2026-11-16.md`.

The Stay primary source was checked against the official archive and its
embedded citation. It assumes five consecutively encrypted compatible files
and reports a typical runtime below two hours on a 500 MHz Pentium II; that is
historical paper evidence, not a METIS or exact-archive benchmark. The
registered ZIP has seven Info-ZIP 3.0 entries, and its seed-derived random
bytes constrain the double-encrypted headers but are not ordinary
Biham–Kocher known plaintext. Stay section 4 specifically exploits the
stream-byte XOR constraints from those double-encrypted bytes across multiple
files. A primary-source cross-check and independent review find the official
seven-member archive's assumptions structurally consistent with section 4
(same-password use is inferred from the single `zip -e` command, and the seed
search matched all seven header observations). The inverse search is not
implemented or validated in METIS; these preconditions do not prove key
recovery. The Stay feasibility report now distinguishes the standard
sandbox (1 CPU/512 MiB) from the ZipCrypto profile (4 CPU/2 GiB, up to 300s per
request). See `reports/issue28-stay-assessment-2026-11-16.md`.

A fresh #39 header audit records the exact limit of this evidence: 7/7 leaked
first-byte matches and one regenerated PRNG sequence, but no enumeration of all
seed matches and no joint full-state consistency test across the encrypted
headers. The independent residual check excludes only a small set of possible
initial stream bytes. Stay key recovery and the official #39 verdict remain
unmet; see the audit section in the linked report.

## Boundaries and remaining work

Issue #1's bounded P0 gate is now accepted for explicit user intake and local
fixtures: exact-head locked install/CI, grant and traversal rejection, private
oracle separation, and the independent trust-boundary audit are documented in
[`p0-acceptance-2026-11-17.md`](reports/p0-acceptance-2026-11-17.md). This does
not establish signed manifest provenance, kernel-escape resistance, or
production readiness.

Issue #6 now also caps each specialist's assigned deadline by the shared run's
remaining wall-clock and has a regression test for parallel dispatch. Shared run
action limits already apply to mediated intents. The CodexCLI driver now
atomically reserves Codex call attempts against a per-run model-turn limit fixed
when the first wave is queued (default 24); concurrency, no-call on
exhaustion, and immutable-run-limit tests pass. Bounded autopilot now fails
closed unless its runner explicitly advertises this controller-side reservation
mechanism. Manual BridgeHost delegation remains outside that guarantee.
Token/cost limits are not enforceable when usage is unknown.
The planner now also refuses to create a subsequent wave after the run-wide
specialist model-turn reservations are exhausted, and synthesis reports that
budget as a blocker. A regression forces the budget to its cap after one wave,
checks the synthesis gate, and confirms no second wave is created. This prevents
planning work that the controller cannot run; it does not change the benchmark
results or establish a multi-agent gain.

The historical 30-task diverse real-model benchmark reported 12/60 multi-arm
workflow-complete oracle solves versus 0/60 single, a 20-point difference
(task-cluster interval [10, 30] points), and 53/60 raw multi-arm oracle hits.
These are unrevalidated historical aggregates: the per-trial data were purged,
so corrected checks for exact assigned-job counts, duplicate records and
distinct repetitions cannot be reapplied. Only multi received an external
controller-computed final digest; equal caps did not isolate specialist count
or match post-processing. The old 12/60 claim must not count as verified
Issue #6 acceptance or satisfy Issue #7's dependency. A fresh experiment with
retained redacted metrics, corrected scoring and equivalent post-processing
was required; a symmetric prospective replication was run on 2026-11-18. Both arms used the same controller-side
component composition and protected-oracle check. Single completed 60/60
workflows and verified 56/60; multi completed only 16/60 and verified 11/60
within completed workflows. Its workflow-complete paired difference was -75
points (task-cluster 95% interval [-86.67, -61.67]); it was faster by 17.112
seconds on average, with materially worse completion and correctness. This
does not meet the paired-gain gate; #6 and dependent #7 remain open. The
answer-free 120-run dataset and reproducible runner/analysis are retained. See
[`issue6-real-model-diverse-benchmark-2026-11-18.md`](reports/issue6-real-model-diverse-benchmark-2026-11-18.md).
The historical asymmetric study remains separately documented and is not
pooled with this symmetric replication.

A candidate/report single-turn specialist action now reduces one potential
model call when both the private candidate and report are ready. It retains the
separate handoff path and checks report text against proposed and pending
candidates, including across correction retries, without exposing candidate
values in output or logs. Focused privacy and retry regressions, the full test
suite, Ruff, and mypy pass. This is a controller optimization, not evidence
that call starvation caused the symmetric result or that multi-agent work now
performs better. The preregistered 30-cluster, three-arm diagnostic has now
completed. Workflow-complete verified outcomes were single 27/30,
multi-separate 8/30, and multi-combined 19/30. Its primary paired gain was
−26.67 points (task-cluster 95% interval [−43.33, −13.33]), so the #6 gain gate
is not met. Combined handoff improved workflow completion versus separate by
43.33 points ([20.00, 66.67]) but raw oracle correctness changed by −6.67 points
([−23.33, 10.00]); combined also had more report rejections (11 vs 9). Therefore
the preregistered full handoff-support rule is not met, and this synthetic
diagnostic does not establish general CTF performance or explain the prior
symmetric result. The answer-free data, deterministic analysis, and results are
retained. Issue #6 and dependent #7 stay open. See
[`issue6-candidate-report-single-turn-2026-11-18.md`](reports/issue6-candidate-report-single-turn-2026-11-18.md),
[`issue6-handoff-diagnostic-results-2026-11-18.md`](reports/issue6-handoff-diagnostic-results-2026-11-18.md),
and [`issue6-handoff-diagnostic-preregistration-2026-11-18.md`](reports/issue6-handoff-diagnostic-preregistration-2026-11-18.md).

Issue #8 now has a strict answer-free retained-metrics schema and analysis CLI
with matched cap checks, complete paired repetitions, contamination exclusions,
independent-verifier provenance filtering, task-cluster intervals and explicit
failure/resource reporting. Its optional read-only ledger reconciliation now
checks every run/sequence reference against the validated event chain and
requires exact successful-verdict provenance tags; browser-attested and local
commitment events do not count as official API verdicts. Its retained 24-row
dataset is invented test data, not a model benchmark or verified solve
evidence. A full controller exporter and fresh held-out experiment remain
necessary; Issue #8 stays open.
See [`issue8-retained-metrics-2026-11-18.md`](reports/issue8-retained-metrics-2026-11-18.md).

For Issue #8, AlpacaHack Daily Misc task `Not so Pyf**k` was first exercised
from its official archive in the no-network, no-host-mount sandbox. The
archive-derived candidate matched the bundled value locally but was rejected
by the official verifier. A candidate read from the single official challenge
instance differed from the bundled value and was accepted by the logged-in
official browser; METIS records the official verdict and the per-problem
write-up answer check matches. This adds one verified solve, but not a repeated
held-out benchmark: repeated runs, confidence intervals, controls, comparable
budgets, cost reporting, and ablations remain outstanding, so Issue #8 stays
open. See
[`issue8-alpacahack-not-so-pyfk-probe-2026-11-18.md`](reports/issue8-alpacahack-not-so-pyfk-probe-2026-11-18.md).

A second official solve, AlpacaHack Daily Web task `RFC100008`, used the
registered Flask archive and one official instance. The instance's automatic
`OPTIONS` response disclosed its generated route method; one exact-method
request reached `/rfc100008`, and the logged-in official browser showed
`Solved`. METIS attestation verified the browser verdict and the write-up
answer check matched. This run was `unlisted`, not preregistered held-out, so
it adds no P7 benchmark result. Issue #8 remains open. See
[`issue8-alpacahack-rfc100008-2026-11-18.md`](reports/issue8-alpacahack-rfc100008-2026-11-18.md).

An earlier 30-case paired synthetic scheduler benchmark verifies the same
tasks in both arms (30/30) and
measures 60 vs 30 deterministic FakeHost provider rounds for a sequential
single assignment vs two dispatched specialists under matched two-turn/two-
action budgets, using a predeclared one-poll-per-assigned-model-turn service
model independent of artifact count. A deterministic `FakeHost` worker now reads only its assigned
artifact subset and itself reserves turns, issues mediated intents, and
submits evidence-backed reports; the test driver advances scheduler ticks and
scores the combined result through the private oracle. This is virtual scheduler
evidence. Explicit `assignment.inputs.artifacts` now also limits artifact names
in each brief, rejects out-of-scope artifact/derive/view intents, and prevents
reports from citing out-of-scope artifacts. A worker's successfully derived
artifact stays scoped to its creating assignment; omitted scopes retain
run-wide access. A follow-up race audit reserves intent identity and turn budget
under a short per-run state lock, runs tools under a separate cancellable
operation lock, then revalidates the assignment and deadline before committing
results or derived scope. Each action carries its own observation sequence so a
concurrent intent cannot claim another action's evidence. Cancellation and
deadlines can stop a running sandbox without waiting for the bounded tool timeout;
canceled and late results are discarded. Regression tests cover concurrent
turn-cap admission, observation attribution, cancellation and deadline races, and
a real Docker integration cancels a running long-lived sandbox worker. The latest
focused suite passed 122 tests with seven
environment-dependent skips; Ruff and mypy passed. `AgentScheduler.tick()` now
polls independent host jobs concurrently within the global and host parallel
limits; a barrier-backed regression proves two declared host slots overlap.
Focused orchestration/autopilot/benchmark validation passed 30 tests, Ruff, and
mypy. The full local suite passed `469 passed, 29 skipped`; skips require
platform features, external distributions, or configured integration images.
This mechanism test does not measure real host latency or model reasoning.
A real-model paired pilot then ran one seeded task through both arms using Codex
CLI 0.169.0:
both candidates verified, while the two-specialist arm took 21.83s vs 20.95s,
used 6 vs 3 provider calls, and used 59,627 vs 29,881 input tokens. This is one
mechanical task with the default model not pinned, so it is not a general
performance estimate and shows no gain. Repeated, diverse, pinned-model runs
with uncertainty and cost reporting remain outstanding. The independent
acceptance review returned NO-GO because the synthetic round-count reduction
is a scheduler model, while the single unpinned real-model pair was slightly
slower and used about twice the calls and input tokens. Issue #6 stays open;
see
[`issue6-model-turn-budget-2026-11-17.md`](reports/issue6-model-turn-budget-2026-11-17.md).
The paired benchmark protocol is in
[`issue6-paired-scheduler-benchmark-2026-11-17.md`](reports/issue6-paired-scheduler-benchmark-2026-11-17.md).
The real-model pilot is in
[`issue6-real-model-paired-pilot-2026-11-17.md`](reports/issue6-real-model-paired-pilot-2026-11-17.md).

Browser verdict attestation now requires a matching pre-reserved candidate;
attestation cannot create a submission record for an unprepared candidate.
Repeated identical verdicts are idempotent and recover the run if a process
stops after persisting the verdict but before the terminal event. This
constrains local state transitions; it does not automate or independently
authenticate what a human saw in the official browser.

Issue #7 now has a seeded declarative-workflow vertical slice: two bounded
encoding families, a closed schema over existing artifact tools, a fixed
no-network sandbox runner, and a controller-side digest check against a private
oracle. The runner returns up to 16 KiB of transformed bytes; the controller
validates encoding, length, and digest before storing them as an untrusted,
run-scoped derived artifact. The real-container integration test and schema,
tamper, and reproducibility checks passed. This is deterministic fixture
evidence, not model-generated research or held-out workflow performance. A
follow-up adds a default-deny, per-run approval for the fixed `rot13_decode`
built-in. An operator must type the exact run/capability confirmation; the
append-only review records bind to a versioned implementation digest, are
revocable, and do not change the global artifact registry. Controller and
sandbox allowlists both enforce the grant; no code, policy, verifier, network,
or deployment extension is accepted. The pinned sandbox test, CLI confirmation,
run isolation, revocation, stale-version, Ruff, and mypy checks pass. This is a
local operator gate, not authenticated maintainer identity or a plugin system.
Issue #7 remains open because the P5 dependency (Issue #6) and broader P6
acceptance remain unmet. See
[`issue7-seeded-workflow-2026-11-17.md`](reports/issue7-seeded-workflow-2026-11-17.md).
The review-gate behavior and evidence are in
[`issue7-capability-review-2026-11-17.md`](reports/issue7-capability-review-2026-11-17.md)
and [`WORKFLOW_CAPABILITIES.md`](WORKFLOW_CAPABILITIES.md).

Issue #5 synthesis now scores support/rejection reports per case-and-whitespace
normalized hypothesis and marks a conflict only when that same hypothesis has
both outcomes. The count difference is not a confidence measure. Structured,
bounded single-tool `next_action_intent` proposals are canonicalized; synthesis
uses that identity for stuckness only when the report cites an observation
sequence recorded for the same controller action. This detects equivalent
single-tool requests despite wording or input-normalization changes without
trusting a proposal hash on its own. Free-text reports retain exact normalized
matching. The same status in adjacent waves signals a stall, and changing
strategy clears it. Exact reused wave rationales are rejected. It does not
infer paraphrased hypothesis equivalence, compare multi-step plans, or choose an
alternative itself. The independent review found the minimum synthetic gate
defensible. Exact-head CI passed on `ad4f87c`; Issue #5 was closed against its
listed minimum gate. Held-out evaluation and real-model baseline comparison
remain open as broader P4 work. See
[`issue5-hypothesis-synthesis-2026-11-17.md`](reports/issue5-hypothesis-synthesis-2026-11-17.md).

Untrusted challenge programs are not executed on the host; dynamic analysis
needs a local container engine and the sandbox image. Earlier validation could
not build the bundled Dockerfile because registries were unreachable; a fresh
Colima profile later built and exercised the image on 2026-11-17. Platforms
other than CTFd, rCTF and ksnctf, and site-specific verdict formats, need the
generic form verifier or a new adapter.

The broader P0-P8 master plan remains a research roadmap. The evidence above
does not establish autonomous solving, broad benchmark performance, comparative
multi-agent gains, or production deployment. Issue #16 now has Linux real-Codex
0.166.0 and 0.169.0 evidence under bwrap and seccomp; the collaborator tool
remains visible but is refused by the tested CLI configuration. The optional standalone
model/container experiments remain separate from the default Codex workflow.
The seccomp regression now checks direct `clone` flag combinations and the
`clone3` fallback on x86_64 and aarch64; CI runs the focused test on both hosted
Linux architectures. This does not expand the tested Codex-version set.

The 2026-11-17 MUNIN increment adds three deterministic synthetic transfer trials
and an ablation comparing one fixed retrieval-guided tool action with two fixed
no-retrieval actions. This covers integration mechanics; it does not measure
model behavior or establish a solve-rate improvement. Run-level split labels are
intake metadata and must be classified correctly. The same increment adds
bounded-autopilot activity counters; cost stays unknown when the provider does
not report it. See `docs/ORCHESTRATION_RUNTIME.md` for operational limits.

Issue #9 now has a local real-container emergency-stop slice: the sandbox
registers its active worker under the per-run lock; cancellation and recovery
remove it, confirm absence with `inspect`, and prevent late results from
overwriting recovered state. Execution cleanup now retains the worker row until
removal and absence are confirmed; unknown cleanup leaves the run executing so
recovery can retry or block. A synthetic failed-cleanup test verifies registry
retention and subsequent recovery. Real Docker integration tests cover cancel
and recover, and a synthetic failure test covers the unknown path. A
process-backed fake-engine test kills controller A, confirms failed
teardown remains recoverable, and verifies controller B recovery plus a
third-process idempotent retry without a fabricated solve. A real-Docker
cross-controller test now kills controller A while its container is running,
then verifies controller B teardown/recovery, retained action charge, no
fabricated solve, and idempotent third recovery. A native macOS controller also
passed this recovery test against the active Colima Ubuntu 24.04/aarch64 Linux
VM (`1 passed in 0.68s`), exercising the Mac-to-VM container path. A separate
fresh-profile recovery drill also passed across VM stop/start. Host reboot,
artifact/credential retention and secure storage remain uncovered; provider-side
token revocation is not tested.
Local synthetic checks confirm per-origin re-auth replaces the prior value and
the next request uses the new Bearer token; `metis web forget URL` removes the
active origin record and the next request sends no Authorization header. The
request test file passed (`5 passed`), along with Ruff and mypy. This does not
invalidate the token at the CTF provider, or prove physical deletion from
SQLite/WAL/backups, retention limits, encrypted storage, or provider-side
rotation. The P7 benchmark release gate also remains uncovered.
A fresh Python 3.12 venv installed the built METIS wheel with
lockfile-exported runtime dependencies; the installed CLI validated a training
manifest and ran a local script in the active Linux VM. A separate fresh
Colima profile then built the sandbox image, ran the wheel-installed CLI with
network/read-only-root/uid probes, and passed a controller-crash recovery drill
across VM stop/start (charged action retained, no solve). This confirms fresh
VM setup and VM reboot recovery, but not a signed VM installer or host reboot.
The interrupted-controller runbook branch is exercised through the actual
`inspect`, `sandbox status`, `codex recover`, and `codex board` CLI commands in
the real-Docker cross-controller test. A separate real-container test now also
invokes `metis codex cancel` against a running worker and confirms teardown,
cancelled run state, retained action charge, and no fabricated solve. This does
not meet the host-reboot or P7 regression gates.
The sandbox/session focused suite passed
(`17 passed, 5 skipped`); real-engine tests skipped there
because no image was configured. Exact PR HEAD `e33d070` passed all checks:
Python CI (`459 passed, 27 skipped`), Docker sandbox integration (`7 passed in
120.72s`), aarch64 seccomp, Ruff, mypy, fixture validation, and build. The
sandbox suite includes the real-Docker cross-controller test.
See `docs/reports/issue9-emergency-stop-recovery-2026-11-17.md`. Issue #9 and
its P7 dependency remain open.

A new read-only `metis audit RUN_ID --database PATH` command projects lifecycle
status, sequence bounds, event timestamps, status counts, and validated chain
integrity without exposing free-form event details. Local CLI checks confirm
private-detail omission, no database writes or missing-file creation, and
fail-closed handling of a corrupt chain. A follow-up adds configured Codex
action/wall limits and charged/remaining action counters from the same read-only
snapshot. Failed and interrupted reservations retain their charge; mutable
session configuration is outside the validated event hash chain. The follow-up
also reports run-scoped job states (including `unknown`), pending action and
model-turn reservations, active-operation and sandbox-worker registrations,
and pending-candidate counts from the same read-only SQLite snapshot. Missing
subsystem tables are marked unavailable; inconsistent model-turn reservation
records and partial reservation schemas fail closed. No identifiers, failure
text, candidate values, paths, or digests are returned. Reservations are not
provider-confirmed usage, and worker registration does not prove liveness. This
still does not provide cost/provider
usage or artifact-retention accounting, and is not a tamper-proof signature or
full operator UI. Focused validation passed: 15 audit tests, Ruff, mypy, and
`git diff --check`. Issue #9 remains open. See the original
[`issue9-read-only-run-audit-2026-11-18.md`](reports/issue9-read-only-run-audit-2026-11-18.md)
and the [unified operational audit](reports/issue9-unified-operational-audit-2026-11-18.md).

A tag-triggered signed-release workflow is now prepared. It validates a strict tag against the project version and main ancestry, builds and checks wheel/sdist metadata, installs the wheel in a fresh environment from hash-locked runtime dependencies, and requires artifact attestations to verify before publishing. Local build, metadata checks, fresh-venv install, CLI version/doctor, workflow YAML invariants, and seven validator tests passed. The workflow has not been triggered; no tag, attestation, or release was created. This does not satisfy signed installer or end-to-end GitHub release acceptance. Host reboot, retention/secure storage, provider-side token revocation, and P7 remain open. See `docs/reports/issue9-signed-release-workflow-2026-11-18.md`.

Sandbox recovery now revokes persisted operation identities after confirmed
teardown. A stale caller must pass its original identity under the launch lock
before registering a worker or accepting results, and cannot replace another
worker row. A barrier regression confirms recovery between reservation and
registration prevents engine launch, preserves the spent action, and permits a
fresh charged execution. Six checks on the pinned Linux arm64 sandbox image
also pass for isolation smoke, cancellation and orphan recovery. Host reboot
and P7 acceptance remain open. See
[`issue9-budget-recovery-fencing-2026-11-18.md`](reports/issue9-budget-recovery-fencing-2026-11-18.md).

Run cancellation is now enforced by the specialist scheduler as well as the
session controller: cancelled runs refuse enqueue, retry, dispatch, model-turn
reservation, new intents, candidate handoff and late reports. In-flight Codex
processes poll the run stop state; already reserved turns remain charged, and
an unconfirmed host stop keeps its slot as `unknown`. A stale completion race
now preserves terminal job states. Assignment/wave cancellation is fenced
between reservation and spawn for fresh and retry attempts; deadline timeout
holds the same lock through confirmed stop and terminal timeout, while expired
reservations are refused before spawn, including expiry while preparing the
host brief. The focused orchestration suites pass 104 tests. The whole suite
passed `565 passed, 31 skipped in 82.89s` on this
host. Remaining skips require Linux
bubblewrap/seccomp, browser dependencies, the #33 PCAP, slow exhaustive search,
or a separate runner/runtime image. Ruff and mypy pass on all changed source
modules. See
[`issue9-run-cancellation-scheduler-2026-11-18.md`](reports/issue9-run-cancellation-scheduler-2026-11-18.md).

`metis codex purge-derived RUN_ID` now previews run-scoped generated artifacts;
`--apply` unlinks only registered `.metis-derived` files and removes their
manifest entries. It refuses active states, operations, workers, queued/running
jobs, and unexpected or symlinked entries. Enqueue/retry and dispatch's
queued-to-running reservation share the per-run lock, closing a race found in
independent review. The retry path reconciles missing files after interruption;
focused tests confirm originals and `.metis-added` files remain. This is local
directory-entry deletion, not secure erasure from snapshots, WAL, or backups. See
[`issue9-derived-artifact-purge-2026-11-18.md`](reports/issue9-derived-artifact-purge-2026-11-18.md).

Phase 4 autopilot has a synthetic one-wave comparison against direct scheduler
calls: both produced four inconclusive specialist reports with matching plan,
enqueue, dispatch, and synthesis counts. Returned activity metrics match their
persisted SQLite row; zero-job token usage stays `unknown`. One autopilot
invocation packages the same control choreography as five direct scheduler
calls, but the test does not measure real human time or solve performance.
Continuation selection and sensitive decisions remain with Daybreak. See
`docs/reports/phase4-autopilot-equivalence-2026-11-17.md`.

An unexpected specialist-driver exception now produces a persisted,
answer-free `specialist_driver_exception` Daybreak handoff. Attempts are left
in their existing running/unknown/queued states because an exception does not
prove that an external worker stopped; a resumed autopilot refuses to dispatch
the queued remainder while a prior attempt needs reconciliation. Synthetic
fault-injection verifies persisted handoff metrics and no redrive. This does
not establish worker liveness or automatic recovery. A mixed completed/crashed
batch regression also verifies that a reserved model call remains charged and
is included in invocation `specialist_turns` using run, assignment, and time
window evidence. The reservation schema does not uniquely attribute concurrent
manual activity on the same assignment. See
`docs/reports/phase4-driver-exception-handoff-2026-11-18.md`.

The Stay forward-relation tests now include a seven-member Info-ZIP fixture
positive case, a second-byte mutation preserving all observed first bytes, and
one deliberately altered PRNG seed. One known shared initial ZipCrypto state
satisfies all seven second-byte relations; the mutated observations and altered
seed are rejected. This validates a forward predicate only, not an unknown-state
search, rejection of all false seeds, inverse search, or #39 key recovery. See
the updated `docs/reports/issue28-stay-assessment-2026-11-16.md`.

Two independent reviews derived the byte-three recurrence and found a
plausible reconciliation: section 5's 26 guesses may exclude the carry, then
add two pass-specific carries. The low-word carry constraints give exact
intervals; a bounded helper and reduced-width exhaustive oracle test their
intersection. The paper's claimed roughly 2^8 surviving `key1_0` values is
still an expected size, not a validated workload. The replacement #39 run's
7/7 PRNG header-byte match still does not recover keys or solve the challenge.
No inverse search is claimed; Issue #28 remains open. See
`docs/reports/issue28-zipcrypto-2026-11-16.md`.

The authorized official archive's complete 2^40 Stay Stage 1 index domain was
then scanned in bounded chunks inside the isolated ZipCrypto profile. The
filter kept 360 private first-stage candidates. A second bounded sandbox
analysis applied the shared-key1 carry interval helper: 88 interval records
remained, with a sum of 98,222,960 interval values before deduplication across
carry choices. This is a Stage 1 reduction only; no Stage 2 filtering, full
key recovery, member decryption/CRC verification with recovered keys, or
official submission occurred. The interval analysis is not yet exposed as a
registered artifact tool. Issue #28 and ksnctf #39 remain open. Full details:
`docs/reports/issue28-stay-assessment-2026-11-16.md` and
`docs/reports/issue28-zipcrypto-2026-11-16.md`.

The Stage 2 partial-state byte-three predictor is implemented and independently
reviewed. A 10,000-case planted full-state oracle test checks its predicted
byte difference; exact-head checks and METIS validation passed at `7921f7f`.
Exact modular floor-sum helpers now compute the `q8` values and second-update
carry bits consistent with each Stage 1 interval without enumerating its 24-bit
range; 500 exhaustive small-word cases and planted interval states verify the
projection. A single-candidate Stage 2 predicate combines all member carry thresholds into
one shared low-residue interval and checks it with a fixed-q8 floor-sum query.
Ten planted seven-file states pass, modified observations fail, and a fixture
with distinct pass carries matches full recurrence. It does not enumerate the
28-bit Stage 2 space. Full key recovery, member CRC checks with
recovered keys, and an official #39 verdict have not occurred. Issue #28
remains open. Details are in
`docs/reports/issue28-stay-assessment-2026-11-16.md`.

A post-implementation aggregate check of the private Stage 1 shards reproduced
360 candidates, 88 carry intervals, and 98,222,960 summed interval values. All
88 intervals admit all 256 `q8` values, so q8 does not reduce the search space.
The check emitted aggregate counts only. Independent review led to a fixed-q8
joint residue query, incremental carry pruning, and a 32,768-visit fail-closed
cap. Distinct pass-carry offsets match the full recurrence. The partial
predicate does not establish the missing high byte of the key2 CRC state;
complete key recovery and all-member CRC validation remain required.

The revised raw Stage 2 domain estimate is 88 interval records × 2^26 partial
guesses = 5,905,580,032 interval/guess pairs before byte-three filtering. This
is an operation count, not a measured runtime or survivor count. A full-member
forward verifier now optionally checks the two known header bytes, the ten
Info-ZIP PRNG bytes after the reset-cipher pass, and the body CRC. Its seven-
member synthetic fixture agrees with CPython `zipfile`; 21 mutations of header
bytes 2, 10, or 11 are rejected. This validates supplied keys only; Stage 2
enumeration, full key recovery, and the official #39 verdict remain incomplete.

Stage 2 now reuses each hit's Stage 1 carry intervals across a bounded chunk
and filters guesses against the first member before traversing intervals. The
planted seven-member sandbox test passed; a separate short zero-hit synthetic
10,000-guess probe reported 0.089 s versus 0.203 s previously. The action cap
still requires at least 5,632 calls for the raw upper domain, and the official
#39 run's wall budget is exhausted. Issue #28 remains open; no official Stage 2
scan or submission occurred. See the Stage 2 interval-reuse section in
[`issue28-stay-assessment-2026-11-16.md`](reports/issue28-stay-assessment-2026-11-16.md).

Issue #9's local `metis web forget URL` path now clears persisted authentication-
origin cookies and fences stale clients from sending or restoring them. State
and generation load share a SQLite snapshot, and initial intake checks the
generation before saving fetched cookies. Credential read/modify/write is
serialized, and browser rendering checks the generation before installing
cookies, on authorized-origin requests, and after rendering. Synthetic tests
cover stale client construction, initial-save interleaving, and forgetting
during rendering; the full local suite, Ruff, and mypy passed at `1f2288f`.
Exact-head CI passed the full suite, static checks, build, sandbox, and ARM64 job.
Real Docker library and CLI cancel rehearsals also passed on the Colima Linux
ARM64 VM. The CLI run confirmed teardown, retained the action charge, and
recorded no solve. This does not establish host reboot recovery.
This does not revoke provider credentials, erase SQLite WAL/backups, clear
user-managed environment variables, or complete P8. See
`docs/reports/issue9-auth-forgetting-2026-11-18.md`.
