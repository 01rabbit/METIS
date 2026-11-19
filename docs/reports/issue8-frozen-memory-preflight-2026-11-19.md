# Issue #8: held-out memory preflight (2026-11-19)

The user authorized online AlpacaHack access when needed. The comparison remains
prospective: no held-out model run or official submission was performed here.

PR #54 freezes the task schedule and checks run evidence, but `KnowledgeBase`
previously returned no MUNIN cards to every held-out run. That would make a
`full` versus `without_memory` arm comparison an ineffective memory ablation.
This change adds an explicit, one-time snapshot of selected existing practice or
competition cards before a held-out run starts work. The default remains empty.
The snapshot stores card payloads and digests, rejects a second freeze, refuses
work-started or non-held-out runs, and checks the stored digest on retrieval.
The run-level controller lock now covers the pre-work event check and the
snapshot transaction together. A concurrent action that attempts to start
while the snapshot is being made waits for the same lock. The regression test
pauses the snapshot immediately after event inspection, starts a second worker,
checks that its action cannot finish, then releases the snapshot and confirms
both operations complete in order.
Held-out results still cannot be written back into MUNIN.

Two official AlpacaHack Rev distributions were downloaded to a temporary local
directory for possible evaluation. Their identifiers are `read-a-binary`
(SHA-256 `20ec2439fb28ef2cb29a4dfd3e83c16c80330df375883333c00323a1b424dcea`)
and `misdirection` (SHA-256
`5d1095cd09dc7c1cf72803673ec4016054a555f623c83e6c5ed177494280a4f1`).
They are x86-64 ELF files; neither was executed. The configured METIS sandbox
reports QEMU user-mode support, no network and no host mounts. The current MUNIN
store has no Rev card, so these tasks are not yet suitable for a meaningful
memory ablation. Before trial execution, establish a relevant independent
practice card, confirm both tasks are unsolved for the evaluation account,
freeze the full protocol and card set, and record its SHA-256 outside the run.
Do not inspect public write-ups before the freeze. Prior model exposure to
these older public tasks is unknown and must be reported as a contamination
limit.

Verification: `PYTHONPATH=src .../pytest -q tests/test_munin_integration.py`
passed 6 tests; Ruff and mypy passed for the changed module. This establishes
the prerequisite snapshot behavior, not Issue #8's repeated-run acceptance
gate. Issue #8 remains open.
