# Issue #6 build-triage pilot rehearsal and preflight

This follow-up implements the model-free preflight for the [build-triage
proposal](issue6-build-triage-study-proposal-2026-11-19.md). It has no real-model
arm. The calibration entry point rejects CodexCLI until a separate reviewed
execution admission is wired in.

## What rehearsal tests

Both workflows send the same canonical artifact, provisional option, output
schema and review instruction. Only the owner-note workflow includes the
private first-stage work note in the review prompt. Both Codex exec calls would
start new contexts. This is a bounded note-access contrast. It does not measure
session continuity, an agent-identity effect or a general multi-agent gain.
A prospective treatment phase should branch both reviewer calls from one
identical provisional output for each task, created before reviewer order is
applied, then score the two final proposals independently. This removes
between-branch variation in the initial diagnosis. It requires review and
registration as a separate study. The present controller rehearses each review
path with the same scripted provisional output, and has no evaluation launcher.

Each phase gets one reserved call in the actual METIS scheduler, one structured
handoff at most, and a monotonic deadline. A controller-generated ledger report
records an accepted handoff without containing model output. No agent tool or
generic controller-intent interface is granted in this workflow. Phase one
accepts an option ID and a separate strict 384-byte private note. Phase two
accepts only an option ID. The verifier receives only the final option and
runs once after two completed handoffs. No verifier feedback enters a prompt.
The 60-second per-phase ceiling is provisional. Evaluate preflight overhead
and the timeout risk for the largest tier before a real launch. If runtime
timeouts jeopardize the calibration completion threshold, disclose that
feasibility result before freezing any revised run design.

The exact UTF-8 prompt and canonical fixture bytes are committed using keyed
HMAC receipts before invocation. The receipt is tied to a scheduler call
reservation and strict output schema. These are controller-side commitments,
without provider attestation. A private in-memory work note is not saved.
The ledger and outcome records contain no option IDs, note, raw prompt,
oracle values or case seeds. Random case labels do not encode fixture hashes.
Retain the 32-byte seed key in private operator storage outside the rehearsal
root until the agreed audit expiry. The controller derives seeds and order
from the key, records a keyed commitment to the complete labeled fixture
schedule, and does not persist the key. Rehearsal rejects duplicate canonical
fixtures and repeated named jobs DAGs before the first call. Before an
evaluation, apply those checks across pilot and evaluation cohorts.
Admission, ambiguity rejection, and a simple observed-duration heuristic
are aggregated by tier and cause family. The heuristic identifies a slow job
only when both its start and finish are present and the elapsed discrepancy
identifies exactly one allowed option. It abstains on other cases.

A calibration claims a fresh private directory exclusively. A repeated call
against that directory is refused whether the previous run completed or was
interrupted. An unfinished prelaunch receipt is deliberately preserved on
exceptions and cannot be resumed through the rehearsal entry point. Before
real execution, the launch authorizer must also prevent replay using the same
approval in a different directory. No operator override or resume path ships
here.

## Offline CodexCLI and Seatbelt preflight

Run the offline preflight with the pinned 0.169.0 executable.

```sh
python -m metis.evaluation.issue6_build_preflight --executable /path/to/codex
```

It verifies native SHA-256
`739cda86e15d30a6e2b40cf8dcbbfb988aaf48b305b27065573bb8e9fd41d002`,
runs the native version command inside Seatbelt, inspects the actual disabled
feature arguments, and exercises Seatbelt deny controls against private paths,
process creation and network egress. The proxy canary refuses the other
host locally. It does not call a model or exercise live model-triggered tool
routing. A future authorized runtime canary must record any tool exposure
before a calibration is admitted. The runtime rejects tool event items and
router errors, and calibration halts on a tool-policy failure.

Only after review and separate launch admission can the fixed 36-case,
single-only calibration run. Its total cap is 72 calls and its purpose is to
select the first predeclared tier with 4–9 of 12 verified and at least 10 of 12
complete. The no-score paired rehearsal exercises both prompt paths without a
model. None of these results satisfy Issue #6's measured-gain gate.
The planned calibration reports observed token usage and makes no hard-token
claim. Issue #8's real held-out launch requirements are independent.
