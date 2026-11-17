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

Terminology: the issue's “Stay 2002” refers to the Springer proceedings
publication year. The work was presented in the FSE 2001 proceedings, and the
paper itself is catalogued as FSE 2001, pp. 125–134. The later 2020 paper is a
distinct differential meet-in-the-middle attack. Keep the algorithms and
their work estimates separate; the 2001 paper's estimate is not evidence for
the 2020 pipeline or a METIS implementation.

The already-cloned `/tmp/metis-breakzip-reference` repository identifies itself
as BreakZip by Mike Stay and Nash Foster and includes a BSD-3-Clause license.
This audit only inspected text/source; no reference scripts, build steps, or
challenge executables were run on the host.

The source is organized as:

1. `mitm_stage1` emits sharded intermediate candidate files.
2. `mitm_stage2` consumes stage-one shards and emits stage-two shards.
3. Stage 3 consumes stage-two candidates and performs final key recovery; the
   repository supplies both `cpu_stage3` and `cuda_stage3` targets.

The supplied shell scripts launch stage two with 96 parallel workers and stage
three through CUDA. The `cpu_stage3.cpp` translation unit includes
`stage3_definitions.h`, which supplies the host implementations of the stage
functions when `__CUDACC__` is not defined. The CPU route is therefore present
in source; the earlier statement in this audit that this file only supplied a
helper and `main` was incorrect. The root CMake project still declares CUDA as
a required project language. The practical upstream CPU-only build remains
unverified; the bounded probe below used a temporary CMake rewrite. No
recovered-key run has been performed. The shown normal run script invokes
`cuda_stage3`. The existing
stage shard files are useful intermediates, but the scripts do not define a
durable checkpoint manifest, atomic checkpoint protocol, resume validation,
cancellation contract, or bounded progress/reason-code interface.

## Bounded CPU build probe (2026-11-17)

To check whether the existing host CPU code can at least compile without a
CUDA toolchain, the Git-tracked upstream source was copied into a temporary
no-network METIS sandbox on `linux/arm64`. The temporary CMake configuration
removed the CUDA project-language requirement and the unavailable Check-based
test target, and selected `cpu_stage3` with the existing stage-one and stage-two
targets. This was a local probe only; it did not alter or validate an upstream
release configuration. Commit `f2e30c525309c7eb60514ecfa42ec58a829d2b22`,
source archive SHA-256
`07f98af2fc96886a5fff975fa7a40e6ee8631a5f78cf4e413be52edca9fc4abb`, and
sandbox image digest
`sha256:fcb7943910b387fb0f441b5d35c97c1b52eee7e98bd56527e4baa997efd0d16f`
are recorded for this probe.

All three targets compiled successfully with GCC 12.2 on Debian Bookworm for
`linux/arm64`. The next step ran BreakZip's own embedded two-file test archive
with `-only_emit_correct`. It exhausted the sandbox's 2 GiB memory limit during
stage one (container reported OOM, exit 247) in 5.74 seconds. No stage-one
shard, later stage, or recovered key was produced. Retrying at the generic
512 MiB limit also OOMed, so the higher-limit attempt did not change the
outcome. This is compile evidence and an observed resource failure, not a
passing synthetic-vector test or proof that a 2 GiB/30-minute adapter meets the
issue's acceptance conditions. The embedded vector is upstream-authored; it is
not an independently generated vector. The #39 archive was not present and no
challenge data was used.

The configured limits constrain the sandbox, but source-level memory bounding,
streaming/shard design, checkpointing, cancellation/progress, and a tractable
independent vector remain unresolved. Keep Issue #28 open.

### Compact Stage 1 bucket prototype (2026-11-17)

A follow-up experiment used a fresh temporary clone of the same upstream commit
and the same embedded two-file vector. It replaced the `2^24`
`vector<vector<stage1a>>` table with a `2^24` array of 32-bit bucket heads and
contiguous candidate/next-index arrays. Only Stage 1 was built in a temporary
CPU-only CMake configuration; no upstream files in METIS were changed. The
probe ran in the METIS `zipcrypto` profile (2 GiB, four CPUs, no network or
host mounts) on `linux/arm64`.

The modified Stage 1a completed and reported 84,148,224 retained candidates.
Stage 1b then exhausted the 2 GiB cgroup limit (exit 137, observed peak
2,147,483,648 bytes) before producing a shard. Thus compacting the bucket
index alone does not meet the resource gate. The result narrows the next
investigation to Stage 1b's accumulation of `stage1_candidate` records: it
currently appends matches to an in-memory vector before writing the shard.
Streaming bounded candidate batches to a temporary shard is a plausible next
experiment, but has not been implemented or validated. There is still no
recovered key, and this upstream-authored embedded vector is not an independent
acceptance vector. No #39 data was used; Issue #28 remains open.

The expert-reviewed next experiment specialized only the upstream self-test's
existing `-only_emit_correct` mode: Stage 1b continued its complete search, but
retained a candidate only when `correct_candidate(*c, g)` matched the known
embedded answer. It required exactly one retained candidate and kept the
normal attack path unchanged. The same test then exited 0 in 8.25 seconds,
reported exactly one correct candidate, and wrote `stage1.0` with a one-record
little-endian count header and 18 total bytes. The cgroup peak was
1,167,056,896 bytes (2 GiB cap), with no network or host mounts, using image
`sha256:bd2742212e2f8c094f787fa421439e90dadfee8c5fecd4b478895523dbeb7133`
on `linux/arm64`. This is oracle-assisted self-test evidence only: the normal
attack path still accumulates all Stage 1b candidates in memory, so it does
not establish the production resource bound or unblock #39. The output file
was validated for its one-record count and serialized length; a full Stage 2
and CPU Stage 3 recovery was not run.

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
- Establish whether the CPU stage-three path builds and passes an independently
  generated two-member vector. The project currently requires CUDA at CMake
  configure time; either make the CPU path a supported build configuration or
  make the CUDA dependency explicit. Fail closed when unavailable.
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
