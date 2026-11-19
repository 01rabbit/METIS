# Held-out token admission gate

The 2026-11-19 exploratory Rev study exceeded its declared 50,000-token cap
in every run. Its Codex CLI runner reports provider usage after a turn, while
the tested CLI interface does not provide a verified bound on both input and
output tokens before dispatch. A post-turn check cannot make the earlier call
fit within the cap.

Real-model held-out runs with a bound prompt now refuse specialist execution
unless the supplied runner explicitly provides hard token-budget enforcement.
`CodexCLI` declares this capability unavailable. This is a fail-closed gate,
not a claim that a working token-controlled runner exists. Synthetic test
runners can declare the capability to exercise the remaining arm-attestation
path, but such tests are not real-model benchmark evidence.

The next study stays on hold until an authorized runner can prove per-call
input and output limits, reserve aggregate tokens atomically across parallel
specialists, reconcile reported usage and interruption, and reject missing
usage. A new protocol must be registered before any new comparison calls.
No separate model API credential is requested by this change.

## Scheduler-bound native admission seam

For a protocol that includes a pinned `llama_backend`, `run_assignment` accepts
only the pinned `LlamaSpecialist` type and requires its admitted-run hook plus
an injected `study_token_admission`. The current `LlamaSpecialist` does not
implement `run_admitted`, so native execution remains unavailable. The path
renders one prompt string and passes
that same value to the scheduler's `persist_receipt` callback and, after a
successful commit, to the runner's `run_admitted` method with its one-time
claim. Inside the scheduler's `BEGIN IMMEDIATE` transaction, the admission
reads the held-out binding, current running job, exact `agent_turn_reservations`
row, model/runtime selection, run budget and applied-arm event. It derives the
study/slot pins from those records and stores only the SHA-256 of the exact
rendered prompt. A mismatch rolls back the scheduler turn and token receipt
before any runner call. Immediately before `run_admitted`, the controller
revalidates the full receipt, confirms the scheduler job and reservation remain
current, and atomically marks the claim consumed; replay and concurrent
consumers fail. A timeout or failed admitted runner leaves both charges intact.
The future runner hook will receive a controller-consumed claim and must only be
reachable through this controller; direct or replayed invocation is outside the
supported path.

The protocol may include an approved `native_manifest_sha256`; the native
admission path refuses to reserve a turn when it is absent. The bookkeeping
charge uses `FULL_CONTEXT_RESERVATION_TOKENS + max_output_tokens`; the shared
context constant also configures the server's context size. The native backend
rejects a tokenized prompt above that value before requesting completion. This
is a conservative reservation used for shared study/run accounting, not
measured token usage and not proof of a provider hard cap. The successful fake-runner tests exercise
only controller plumbing. No production runner currently implements
`run_admitted`, `LlamaSpecialist.hard_token_budget_enforced` remains false, and
no model was launched. Real-model held-out execution remains refused until a
reviewed runner accepts only a controller-consumed claim and establishes its
own pre-dispatch token bound.

The admitted runner's server startup now shares the call's monotonic deadline
and scheduler stop callback. Cancellation during health polling terminates the
server process group and records a cancelled outcome; the call deadline bounds
startup plus tokenization and completion together. Startup cancellation and
deadline expiry are covered with a delayed local fake server. This closes the
local wait-boundary gap but does not change the runner's `hard_token_budget_enforced`
declaration or authorize a real-model held-out trial.
