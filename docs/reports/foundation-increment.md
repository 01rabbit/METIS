# Foundation increment review

Problem: initial manifest contracts accepted unexpected fields, numeric true,
non-finite costs and nonportable artifact paths. The CLI exposed rejected input
in validation errors; lifecycle state could not be persisted or inspected.

Changes: strict policy fields and explicit authorization; exact endpoint parsing;
portable artifact path validation; controller-only SQLite evidence with explicit
transitions and validated JSONL export; prepare/inspect CLI; tests and CI.
See ADR 0003 for trust assumptions and limitations.

Validation: 75 local tests exercise schema rejection, local endpoint acceptance,
CLI rejection without input disclosure, persistent replay, concurrent sequence
collisions, invalid-transition rollback, terminal states, append-only triggers,
corruption detection and read-only inspection, descriptor-based artifact reads,
and the restricted Docker runtime. Type checking covers 7 source files.
The initial 6 tests also remain passing. No benchmark solve-rate is reported.

Local results before final cleanup review: 75 passed, zero skipped; Ruff passed; mypy passed for all 7
source files; sdist/wheel build and `git diff --check` passed. GitHub Actions has
not been observed. A prior integration assertion was corrected to match Docker's
case-insensitive missing-container error text, then the full suite was rerun.
Final cleanup review subsequently detected a late-create race in `docker run`:
timeout removal could race creation and leave a stopped container. The runner
now completes `docker create` before invoking deadline-bound `docker start -ai`.
A creation timeout is an explicit unresolved infrastructure error. Cleanup of
normal execution timeouts is tested against already-created containers.

After that fix: all 75 cases passed again with zero skips, mypy and Ruff passed,
the package rebuilt successfully, and a final daemon query found no remaining
`metis-fixture-*` containers. The review branch was pushed to GitHub; Draft PR
creation returned `Forbidden` from the GraphQL API and remains outstanding.

Security review: no challenge executables are executed and no network client or
shell tool is exposed. Three fixed transforms operate on bounded input strings.
Endpoint syntax does not implement DNS or connection authorization. Descriptor
artifact reads reject symlinks, special files and oversized input. SQLite
triggers/hashes are not protection from a database owner.
Event detail strings require caller discipline; no general secret sanitizer or
full solver/verifier protocol is implemented. SOLVED transitions are controller-only
metadata, not an independent verifier verdict. This API must not be exposed to
the solver. Preparation can leave a NEW record if its second append fails.

Review scope: this increment advances P0 and lifecycle prerequisites; it does not
fulfill P0–P8. No phase Issue is eligible for closure from this evidence alone.
Outstanding external review/model prerequisites are listed in `docs/STATUS.md`.

Container evidence: official Python image
`python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`.
Six executed integration cases cover two decoding transforms, SHA-256, invalid
input, host oracle/socket/secret denial, non-root/read-only/no-network operation,
and timeout removal confirmed through a subsequent container inspection. The
probe uses synthetic test-only oracle contents. It does not establish protection
against kernel exploits or a complete adversarial sandbox evaluation.
