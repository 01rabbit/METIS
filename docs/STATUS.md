# METIS implementation status

## Current increment

Branch: `metis-full-implementation` (the requested `work/...` namespace conflicts
with the existing local `work` branch).

Implemented: fail-closed contract validation, portable relative artifact path
syntax, exact endpoint syntax, controller-owned append-only lifecycle storage,
hash-chain validation, transactional sequence/transition enforcement, JSONL
export, `metis prepare`, read-only `metis inspect`, and CI check definitions.
CLI errors no longer echo rejected manifest contents.

Also implemented: descriptor-based bounded artifact reads rejecting symlinks and
special files, SHA-256 digests, and a restricted Docker fixture runtime supporting
only Base64/hex decoding and SHA-256. The runtime has no host mounts, no network,
a read-only filesystem, dropped capabilities, non-root UID and bounded resources.
Arbitrary commands/binaries are unsupported. Timeouts force container removal;
unconfirmed cleanup raises an infrastructure error.

Local Linux checks: see the implementation report for final test counts,
lint/type/build results, and the pinned container image used. No GitHub CI
result, live-model solve, isolation evaluation, or macOS validation is claimed.

## Phase gates and remaining work

| Phase | Evidence and remaining requirements |
| --- | --- |
| P0 | Partial. Contracts, bounded artifact snapshots, development checks, lifecycle evidence and a restricted fixture runtime exist. Container tests establish host-oracle path denial for this runtime; a full solver/verifier protocol and adversarial isolation evaluation remain. |
| P1 | Not accepted. Lifecycle persistence and inspection exist; autonomous loop, isolated runtime, verifier, cancellation and real-model two-category solves remain. |
| P2 | Not started; requires accepted P1 baseline. |
| P3 | Not started; requires P1 and an independently protected evaluation boundary. |
| P4 | Not started; requires P1/P3 with measured baseline. |
| P5 | Not started; requires P2/P4 and global budget enforcement. |
| P6 | Not started; requires P3/P5 and human-reviewed extension publication. |
| P7 | Not started; requires prior gates, held-out evaluator and repeated trials. |
| P8 | Not started; requires evaluation evidence and actual Linux/macOS deployment validation. |

## External blockers observed

- Git read of `origin HEAD` succeeds. GitHub GraphQL and REST Issue reads through
  existing authentication return `Forbidden`; a GitHub web Issue request returns
  404. Issue #1–#9 contents therefore remain unverified. No issue was closed or
  modified, and no PR has been created. The GitHub plugin has no callable tools
  in the current session. Restore scoped GitHub Issue/PR access to complete the
  requested external review workflow; do not assume a new raw token is required.
- `OPENAI_API_KEY` is absent in the runtime and no model binding is declared in
  environment status. A live-provider P1 acceptance run cannot be performed yet.
  Configure credentials securely in environment settings when that runner exists;
  never enter secret values in chat. No paid model request has been made.

These external blockers do not imply that the unfinished local implementation
is complete. Continue with a protected verifier protocol, budget enforcement and
the model/tool loop before autonomous solves; do not bypass acceptance gates to
claim later phases.
