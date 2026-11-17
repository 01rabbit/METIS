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
mechanism evidence; generalized hypothesis scoring, contradiction/stuckness
handling, semantic repeat detection, diverse held-out tasks, and real-model
comparison remain open. See
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
exact head `9465732`). It reports a route-level `sandbox-oom` stage because startup/import/search
phases are not distinguished. A new synthetic memory-pressure test in the
actual 2 GiB ZipCrypto profile observed the cgroup OOM marker, mapped it to
`memory_limit_exceeded`, and confirmed worker-registry cleanup. This validates
production-profile OOM classification and cleanup, but does not show a natural
ZipCrypto candidate search reaching the limit. The final listed #28 resource
acceptance item is now met: the real-worker deadline and production-profile
synthetic cgroup OOM tests return bounded reason codes and clean up. All three
listed acceptance checkboxes are checked; the Issue remains open because Stay
key recovery and ksnctf #39 remain unresolved. One full intent search in the isolated
route recovered keys, checked both members' plaintext and CRC, then decrypted
and XORed (`1 passed in 34.27s`); a different synthetic input exceeded its
300-second budget. Container creation, engine attach, and OOM inspection timeout
results now map to `worker_failed` with their infrastructure phase; only the
in-container supervisor's workload deadline maps to `work_exceeds_budget`. Fake-engine phase tests and
real-container deadline/OOM tests pass. Stay recovery, OOM phase attribution,
and natural candidate-search OOM remain unproven. The 2020 two-file attack's
paper and legacy CUDA source were reviewed, not run. Docker-backed budget and
full-intent integration checks now run in a dedicated GitHub Actions job.
See `docs/reports/issue28-zipcrypto-2026-11-16.md` and
`docs/reports/issue28-stay-assessment-2026-11-16.md`.

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
Token/cost limits are not enforceable when usage is unknown. A 30-case paired
synthetic scheduler benchmark verifies the same tasks in both arms (30/30) and
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
environment-dependent skips; Ruff and mypy passed. The scheduler polls workers
serially, so the benchmark
does not measure real elapsed time, concurrent tool execution, or model reasoning.
A real-model paired pilot then ran one seeded task through both arms using Codex
CLI 0.169.0:
both candidates verified, while the two-specialist arm took 21.83s vs 20.95s,
used 6 vs 3 provider calls, and used 59,627 vs 29,881 input tokens. This is one
mechanical task with the default model not pinned, so it is not a general
performance estimate and shows no gain. Repeated, diverse, pinned-model runs
with uncertainty and cost reporting remain outstanding. Issue #6 stays open;
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
evidence, not model-generated research or held-out workflow performance. Issue
#7 remains open. See
[`issue7-seeded-workflow-2026-11-17.md`](reports/issue7-seeded-workflow-2026-11-17.md).

Issue #5 synthesis now scores support/rejection reports per case-and-whitespace
normalized hypothesis and marks a conflict only when that same hypothesis has
both outcomes. The count difference is not a confidence measure. Synthesis now
also detects the same normalized action and hypothesis with the same single
status in consecutive waves; a current strategy change clears the signal.
Exact reused wave rationales are rejected. It does not identify paraphrased
strategies or select an alternative itself. Held-out evaluation and real-model
baseline comparison remain open. Issue #5 stays open. See
[`issue5-hypothesis-synthesis-2026-11-17.md`](reports/issue5-hypothesis-synthesis-2026-11-17.md).

Untrusted challenge programs are not executed on the host; dynamic analysis
needs a local container engine and the sandbox image. The bundled Dockerfile
build itself was not run in validation because registries were unreachable
there. Platforms other than CTFd, rCTF and ksnctf, and site-specific verdict
formats, need the generic form verifier or a new adapter.

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
fabricated solve, and idempotent third recovery. Host reboot, artifact/secret cleanup,
Linux VM deployment, or the P7 benchmark release gate remain uncovered. The sandbox/session
focused suite passed (`17 passed, 5 skipped`); real-engine tests skipped there
because no image was configured. Exact PR HEAD `e33d070` passed all checks:
Python CI (`459 passed, 27 skipped`), Docker sandbox integration (`7 passed in
120.72s`), aarch64 seccomp, Ruff, mypy, fixture validation, and build. The
sandbox suite includes the real-Docker cross-controller test.
See `docs/reports/issue9-emergency-stop-recovery-2026-11-17.md`. Issue #9 and
its P7 dependency remain open.

Phase 4 autopilot has a synthetic one-wave comparison against direct scheduler
calls: both produced four inconclusive specialist reports with matching plan,
enqueue, dispatch, and synthesis counts. Returned activity metrics match their
persisted SQLite row; zero-job token usage stays `unknown`. One autopilot
invocation packages the same control choreography as five direct scheduler
calls, but the test does not measure real human time or solve performance.
Continuation selection and sensitive decisions remain with Daybreak. See
`docs/reports/phase4-autopilot-equivalence-2026-11-17.md`.
