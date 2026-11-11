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
Arbitrary commands/binaries are unsupported. Resource enforcement is checked
before creation and in the container; unavailable enforcement refuses execution.
Timeouts force container removal;
unconfirmed cleanup raises an infrastructure error.

Local Linux checks: see the implementation report for final test counts,
lint/type/build results, and the pinned container image used. No GitHub CI
result, live-model solve, complete isolation evaluation, or macOS validation is claimed.

The next increment adds a bounded provider-neutral plan/tool/verify loop,
controller-owned action/token/cost reservations and deadlines, repeated-action
stopping, cancellation markers, an independent private fixture oracle, two
generated categories and an optional OpenAI JSON adapter. `uv.lock` pins runtime
and development dependencies. CLI `run` and `generate-fixtures` are implemented.
Actual decoded candidates and raw exception text are never written to events.

Current validation after hardening: 86 tests passed, 8 container cases skipped
because this daemon reports `CgroupDriver=none` (rootless, cgroup v2 without
delegation). The runtime now refuses execution in this environment. Earlier
functional trials solved both generated categories before the enforcement check
was added; these are NOT proof of resource isolation or current readiness.
CI requires those container tests and fails, rather than skips, if unsupported.

## Phase gates and remaining work

| Phase | Evidence and remaining requirements |
| --- | --- |
| P0 | Partial. Contracts, bounded artifact snapshots, locked setup, lifecycle evidence, an independent local oracle and a restricted fixture runtime exist. Required resource isolation cannot currently be validated on this daemon; no full issue closure is claimed. |
| P1 | Not accepted. Plan/tool/observe/verify loop, budgets, cancellation and optional OpenAI adapter exist. Requires enforced Docker quotas, live-model two-category validation, durable execution resume and broader tool support. |
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
  the running environment. `METIS_OPENAI_API_KEY` is also absent. A draft now
  declares `METIS_OPENAI_API_KEY` restricted to `api.openai.com`, and that domain
  was added to the draft. Supply the value securely in environment settings,
  review/save changes and publish; no real API call has been made.
- The managed daemon is rootless with `CgroupDriver=none`. A non-root task user
  cannot enable cgroup delegation or replace it with a privileged daemon. Recover
  or provide an environment with enforced cgroup v2 CPU/memory/PID limits. No
  privilege escalation or weaker sandbox fallback was attempted.

Reusable install/start instructions and the pinned test image variable were
saved successfully in the environment draft. This supersedes the earlier draft
save failures. Saving neither applies them to this instance nor publishes them.

These external blockers do not imply that the unfinished local implementation
is complete. Durable execution resume, adversarial boundary review and broader
tools remain local implementation work. Do not bypass acceptance gates or claim
later-phase completion from deterministic synthetic fixtures.
