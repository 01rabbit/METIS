# Issue #28: Stay reference and bounded-run audit (2026-11-17)

## Decision

Do not expose a Stay recovery tool yet. The available reference is a staged
GPU-oriented research implementation, not a portable CPU worker that can be
placed behind the current sandbox request. Its documented 2020 paper algorithm
and its implementation have not been independently reproduced here. A seed
match or the existing Biham–Kocher tests do not validate Stay key recovery.

This audit is the concrete partial deliverable for this checkout. It makes no
recovery claim and does not add a tool that could return an unverified key.

## Reference source

The already-cloned `/tmp/metis-breakzip-reference` repository identifies itself
as BreakZip by Mike Stay and Nash Foster and includes a BSD-3-Clause license.
This audit only inspected text/source; no reference scripts, build steps, or
challenge executables were run on the host.

The source is organized as:

1. `mitm_stage1` emits sharded intermediate candidate files.
2. `mitm_stage2` consumes stage-one shards and emits stage-two shards.
3. `cuda_stage3` consumes stage-two candidates and performs final key recovery.

The supplied shell scripts launch stage two with 96 parallel workers and stage
three through CUDA. Although a `cpu_stage3` target exists, the repository build
requires CUDA, its `cpu_stage3.cpp` only supplies a helper and `main`, and the
shown normal run script invokes `cuda_stage3`. The CUDA stage is the completion
path in the supplied scripts. The existing stage shard files are useful
intermediates, but the scripts do not define a durable checkpoint manifest,
atomic checkpoint protocol, resume validation, cancellation contract, or
bounded progress/reason-code interface.

The inspected source also documents assumptions that must be resolved before
an adapter can safely accept arbitrary METIS artifacts: stage-three code
comments that the MITM structures support only two files, and stage-three
derives the first 10 random bytes from a supplied `srand` seed. The current
ksnctf #39 archive has seven members. The source's test ZIPs and build scripts
were not treated as an independent synthetic-vector validation of a METIS
integration.

## METIS sandbox fit

`src/metis/core/ctf_sandbox.py` creates a fresh container with no network, no
host mounts, read-only root, a 256 MiB executable work tmpfs, 1 CPU and 512 MiB
memory. `SandboxRequest.timeout` is capped at 300 seconds. Its response model
returns bounded process streams but no files produced inside the container;
the temporary container is removed at completion. Thus it cannot currently
preserve the reference's multi-stage shard files across invocations, and its
resource envelope does not meet 2 CPUs / 2 GiB / 30 minutes.

The Docker daemon visible during this audit reports 4 CPUs and about 5.8 GiB
host memory, but host capacity is not proof that a configured isolated test
container can provide the requested quotas. This worktree has no sandbox image
configuration, so no isolated reference execution was attempted.

## Required work before implementation

- Independently derive small synthetic encrypted archives and expected keys
  from the ZipCrypto state equations; test the complete reference pipeline
  against those vectors inside a pinned no-network image.
- Establish whether the CPU stage-three path is complete and supported, or
  make the CUDA dependency an explicit required capability. Fail closed when
  unavailable.
- Restrict supported archive/member layout, validate seed and both member
  headers, then validate recovered keys by decrypting members and checking
  CRCs before returning `found`.
- Add a dedicated sandbox profile without changing generic sandbox defaults:
  hard 2-CPU / 2-GiB / 1800-second limits, bounded disk and candidate counts,
  no network or host mounts, and output size limits.
- Persist checkpoints outside the disposable container only after validating
  schema/version, input digest, source digest, stage/shard identity, and
  integrity. Use atomic writes and reject mismatched or partial checkpoints.
- Define cooperative cancellation at stage/shard boundaries, progress counters,
  and stable outcomes such as `recovered`, `no_solution`, `unsupported_layout`,
  `time_budget_exceeded`, `memory_or_disk_budget_exceeded`, `cancelled`,
  `checkpoint_invalid`, and `worker_failed`. Exhaustion and interruption must
  never be presented as a successful recovery.

Until those conditions are met and independently tested, keep Stay key
recovery unavailable and leave Issue #28 open.
