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
