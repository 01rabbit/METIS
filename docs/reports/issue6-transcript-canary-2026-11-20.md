# Issue #6 fixed-transcript guardian canary (2026-11-20)

The offline transcript canary drives a fixed public Codex JSONL stub through the
same guardian boundary used by the public dry-run worker. It exercises sanitized
completion, invalid response, tool-policy rejection, capture limits, deadline,
cancellation, terminal evidence rollback, and controller death. It does not
launch a model or establish a measured multi-agent gain.

A macOS race was reproduced where `killpg` can report `EPERM` after the direct
child exits but before the guardian waits for it. The reap path now proceeds to
`wait`; a live child that cannot be killed still fails the bounded wait instead
of receiving a false terminal record. A deterministic regression test covers
that error path, and the guardian deadline/overflow race cases passed ten
consecutive focused repetitions after the fix.

A transcript canary cancelled before child launch now records a terminal
cancelled/deadline outcome without claiming a child was reaped. The evidence
projection's per-run HMACs redact values but their random key is discarded, so
they cannot be verified later or used as cross-run commitments. `reaped_at`
means the direct child was waited for; it does not prove that a process group is
empty. Current canary workers prohibit creating child processes.

This is process/evidence plumbing only. It does not execute Codex, prove
provider-side behavior or token billing, or satisfy Issue #6's measured-gain
acceptance gate. Issue #6 and dependent Issue #7 remain open.
