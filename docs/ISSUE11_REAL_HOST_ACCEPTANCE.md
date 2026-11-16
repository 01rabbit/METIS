# Issue #11 — real-host acceptance protocol

This is a **manual acceptance gate**, not evidence that a real Codex or Claude subagent has run.
The repository's synthetic/fake-host tests and CI are necessary but do not prove host-side
execution, policy compliance outside the METIS CLI, or end-to-end orchestration.

## Prerequisites

Use a disposable, authorized local synthetic challenge with at least two categories
(e.g. crypto and forensics) and two benign distribution files. Use Python 3.12+,
a fresh METIS state database, and an installed Codex or Claude Code CLI. Do not use
real credentials, private flags, or external challenge endpoints for this test.
Capture the host CLI name and version, METIS commit, UTC timestamp, and OS.

## Procedure

1. In the selected host, open METIS with `./start` and follow `AGENTS.md`.
   Run `metis doctor`. Record whether the host exposes an actual subagent API.
2. Intake the synthetic challenge with the documented `metis intake` flow.
   Run `metis plan RUN_ID` and assert `execution_mode=delegated` and two to
   four distinct bounded assignments.
3. Run `metis agent dispatch RUN_ID WAVE_ID`. Pass the returned **individual**
   briefs to two real host subagents using the host's supported delegation tool.
   Record actual host job identifiers, model identifiers as reported by the host,
   and any capability/slot fallback. **Do not** claim a real spawn if only a
   brief was returned.
4. Ask each subagent to request one allowed, bounded artifact/data analysis
   through `metis agent intent`, then to submit a compact report through
   `metis agent complete`. The controller must be the sole writer.
   Confirm the reported evidence sequence exists in the run event ledger.
5. Attempt a forbidden specialist intent (`submit` or `grant`) and confirm
   the controller rejects it. This only validates the METIS boundary; inspect
   host traces separately for direct shell/network actions outside that boundary.
6. Run `metis agent synthesize RUN_ID WAVE_ID`; confirm no missing required
   assignments, no implicit submission permission, and no candidate/credential
   in the ledger. If a worker fails, record the terminal state and require
   explicit resolution rather than silently treating it as success.
7. Repeat with an interrupted worker: cancel, restart the METIS controller,
   run `metis agent tick`, and verify stale attempts are rejected and slots
   are not released without confirmed termination.
8. Run the synthetic official-verdict rehearsal (correct, incorrect, unknown,
   429, auth) using existing local fixtures, not an external service. Verify
   that an incorrect result requires a distinct revised test before resubmission.
9. Inspect the SQLite ledger, Git working tree, MUNIN cards, and generated
   reports for credential/flag/private-data leakage. Redact evidence before
   attaching logs.

## Acceptance record

| Gate | Required evidence | Status |
| --- | --- | --- |
| Host actually launches 2 distinct subagents | Host job IDs and sanitized trace | NOT RUN |
| Bounded dispatch/intent/complete/synthesize | CLI output and event sequence | NOT RUN |
| Specialist authority boundary | Rejection output and host trace | NOT RUN |
| Cancel/restart/stale attempt | State transitions and event log | NOT RUN |
| Official verdict and revision | Local fixture trace | NOT RUN |
| No secret persistence | Redacted inspection results | NOT RUN |
| Python 3.12 CI, Ruff, mypy, build | GitHub Actions run URL | PASS for PR #13 CI; verify main run separately |
| Manifest validation | Canonical command and output | NOT RUN |

Do not mark Issue #11 complete solely from this document. Attach a dated,
sanitized record with actual results, failures, skips, and limitations. The
host's own unrestricted shell is outside METIS CLI enforcement; document this
as a residual risk, not a passing security guarantee.

## Review links

- Issue: https://github.com/01rabbit/METIS/issues/11
- Validation PR: https://github.com/01rabbit/METIS/pull/13
- Runtime design: [ORCHESTRATION_RUNTIME.md](ORCHESTRATION_RUNTIME.md)
