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

### AlpacaHack Daily held-out probe (2026-11-17)

The user-authorized unsolved `zen.zip` Daily archive was added to a separate
held-out METIS run. Using the public first 32 bytes of “The Zen of Python” as
known plaintext for `zen.txt`, the fixed ZipCrypto worker ran inside the
configured `linux/arm64` 2 GiB/no-network/no-host-mount profile. After
correcting phase attribution for spawned workers, the attack reported
`work_exceeds_budget` at 60.057 seconds in `candidate-key-search`. After
correcting phase attribution, the same bounded attack was extended once to
the 300-second tool limit and again returned `work_exceeds_budget` in
`candidate-key-search` at 300.103 seconds. No key or plaintext was recovered
and no official submission was made. This is a real held-out negative result
for the standard known-plaintext route; it does not test or establish Stay
key recovery. A final bounded attempt supplied 80 exact bytes generated by
the installed Python `this` module (the same 857-byte `zen.txt` source) to give
candidate reduction more known plaintext. It again reached `candidate-key-search`
and returned `work_exceeds_budget` at 300.081 seconds, with no recovered key
and no official submission. More known plaintext alone did not make this
route finish within the tool cap.

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

### Count-only Stage 1b volume diagnostic (2026-11-17)

A temporary count-only variant of the compact Stage 1 implementation was built
and run against BreakZip's embedded two-file self-test in the pinned METIS
`zipcrypto` sandbox (`linux/arm64`, 2 GiB memory, four CPUs, no network, no
host mounts, 300-second limit). The diagnostic completed in 8.127 seconds
without a sandbox timeout or OOM. Stage 1a retained 84,148,224 entries; Stage
1b visited 20,804,384 candidate records and found exactly one match against
the self-test's embedded known answer. It retained and wrote no candidate
records.

Using the upstream serializer's exact record layout (8 fixed bytes plus three
bytes per `k20` value) and four-byte per-shard count header, the full candidate
set would occupy 420,223,804 bytes across 21 shards at the default one-million
record shard size. That exceeds METIS's current 256 MiB `/work` tmpfs by
151,788,348 bytes. The diagnostic provides an output-volume measurement; it is
oracle-assisted self-test evidence, not a recovered key or independent
cryptanalytic validation. It does not implement shard streaming, persistent
checkpoints, resume validation, cancellation, or a usable multi-stage data
channel. Therefore it does not satisfy Issue #28's acceptance gates, and no
change to the production worker or sandbox resource defaults is justified.

#### Reproduction materials for count-only diagnostic

The exact temporary source change is preserved in
[`issue28-breakzip-countonly.patch`](issue28-breakzip-countonly.patch)
(SHA-256 `ea38e73e404663b62e099838bc3a65c4328ca0a1b3110fc60acab23cc542b83c`).
It applies to the public BreakZip source at commit
`f2e30c525309c7eb60514ecfa42ec58a829d2b22`. The data-only source tarball
used for the build, excluding `.git` and `third-party/`, had SHA-256
`3498a97b58745108909a60a7423453cc5e9cfd7fe6d7cfd1e139687716d1e1f3`.
The pinned image was
`sha256:bd2742212e2f8c094f787fa421439e90dadfee8c5fecd4b478895523dbeb7133`
(`linux/arm64`); its in-container compiler was GCC 12.2.

The sandbox build request used `mode="script"`, `interpreter="sh"`,
`timeout=300`, and `_profile="zipcrypto"`. The build script was:

```sh
set -eu
mkdir -p /work/src
tar -xzf "$METIS_TARGET" -C /work/src --strip-components=1
python3 - <<'PY2'
from pathlib import Path
p=Path('/work/src/CMakeLists.txt')
s=p.read_text().replace('project (breakzip CUDA CXX)','project (breakzip CXX)')
s=s.replace('find_third_party_pkg(check)','')
s=s.replace('SET(CMAKE_CUDA_TOOLKIT_INCLUDE_DIRECTORIES src/cuda_common/inc /usr/local/cuda/include)','')
p.write_text(s)
p=Path('/work/src/src/CMakeLists.txt')
s=p.read_text().replace('add_subdirectory(test)','').replace('add_subdirectory(gpu_stage3)','')
p.write_text(s)
PY2
cmake -S /work/src -B /work/src/build.out -DCMAKE_BUILD_TYPE=Release >/dev/null 2>&1
cmake --build /work/src/build.out --target mitm_stage1 -j2 >/dev/null 2>&1
base64 -w 0 /work/src/build.out/src/mitm_stage1/mitm_stage1
```

The controller decoded that build artifact without executing it on the host,
then intook it as a declared artifact and ran it in a second fresh sandbox
request using `mode="run"`, `args=["--count_only=true", "--test_archive=0"]`,
`timeout=300`, and the same `zipcrypto` profile and image. The returned stdout
was exactly:

```json
{"ok":true,"stage1a_entries":84148224,"stage1b_candidates":20804384,"correct_matches":1,"serialized_candidate_bytes":420223720,"shards":21,"serialized_file_bytes":420223804}
```

The serializer stores each record as eight fixed bytes plus three bytes per
`k20` value. The measured byte total therefore corresponds to 84,596,216
aggregate `k20` values. The 21 shard headers add 84 bytes. These figures allow
recomputation of the 420,223,804-byte total without retaining or exporting any
candidate or key material. Reproduction still validates only an upstream
self-test; it is not a Stay solve or an independent attack vector.

### Oracle-assisted Stage 1 → Stage 2 handoff probe

A follow-up checked that the known-correct Stage 1 record can be passed through
the upstream Stage 2 executable inside one sandbox request. The source was the
same public BreakZip commit above, packaged without `.git` or `third-party/`
(archive SHA-256
`5e83f269746602716535296e17c1c6903a2e8fd397a51e49326e96118ce30d63`). The
count-only patch above was applied, followed by
[`issue28-breakzip-only-correct.patch`](issue28-breakzip-only-correct.patch)
(SHA-256
`afa23ddfb65d5546a7832b26cedeebe86babeda9803750de5e36e232f96936e7`). For
this test-only patch, `-only_emit_correct` retains only the embedded test
oracle's known-correct Stage 1 record; this intentionally avoids storing the
other 20.8 million candidates. This is oracle-assisted filtering, not an
attack-mode streaming implementation.

The sandbox compiled both targets and ran the embedded Stage 1 test, then fed
its 18-byte `stage1.0` shard to Stage 2 with `-only_emit_correct=true` and
`-stop_after=0`. Stage 2 processed that one Stage 1 record, enumerated 1,988
Stage 2 candidates, and emitted the single oracle-matching record in a 25-byte
`stage2.0` file. The complete request took 10.675 seconds and reported a
container `memory.peak` of 1,170,993,152 bytes under the pinned linux/arm64
2-GiB, 4-CPU, 300-second profile; network was disabled and there were no host
mounts. No challenge archive or candidate material was exported. The build
binary ran only inside the sandbox.

This validates a one-record file-format and Stage 1/2 handoff. It does not
exercise a full 1-million-record shard, repeated shard deletion, full Stage 2
coverage, Stage 3 key validation, candidate streaming, checkpoint/resume, or
Stay recovery. It therefore does not establish that the 420,223,804-byte
candidate set can be processed end-to-end within the current disk, memory, and
time limits, and does not change the Issue #28 decision.

### Unfiltered Stage 2 count-only prefix probe

Following independent expert advice, a second bounded probe measured Stage 2
without the oracle filter and without writing Stage 2 candidates to files. The
temporary patch
[`issue28-breakzip-stage2-countonly.patch`](issue28-breakzip-stage2-countonly.patch)
(SHA-256
`578c936ab9b33b60418b9738a718bb0472f67ee330d87d053ea6dc0baa48059a`) was
applied after the count-only patch. It wrote only the first 1,000 Stage 1
records to a transient `/work/stage1.0` prefix shard, then counted Stage 2
outputs in memory without merging or serializing them. The source archive was
the same pinned commit and SHA-256 recorded above.

On the pinned `linux/arm64` image with the 2-GiB memory, four-CPU, 256-MiB
`/work`, no-network profile, Stage 1 counted 20,804,384 candidates and retained
only a 20,175-byte 1,000-record prefix. Stage 2 had a 40-second subprocess cap:
it processed 85 records, counted 300,018 Stage 2 candidates, then hit the cap.
The sandbox request completed (including build and Stage 1) in 49.505 seconds;
container `memory.peak` was 1,174,577,152 bytes. `/work` used 2,239,755 bytes
before Stage 2 and 2,219,580 bytes after the prefix shard was deleted. Stage 2
candidate outputs were not written or exported.

**Feasibility decision: NO-GO for the upstream default 1,000,000-record Stage 1
shard under METIS's 300-second sandbox request limit.** The observed prefix rate
was 2.125 Stage 1 records/second. A linear extrapolation would take about
130.7 hours per default shard; this estimate is only a warning signal because
the first 85 Stage 1 records are not a random sample and candidate counts vary.
Even without extrapolation, processing only 85/1,000 of the bounded prefix
already used 40 seconds. A useful next step would require a different
algorithm or much cheaper Stage 2 reduction; merely streaming Stage 1 output
does not resolve the measured Stage 2 throughput bottleneck.

This remains an upstream embedded self-test and a feasibility probe, not an
independent vector, Stage 3 key validation, Stay recovery, or a #39 solve. The
test-only patch must not be treated as a production worker change. At the time
of this audit, the KSNCTF #39 distribution was unavailable in this environment;
the official distribution was later acquired and analyzed as recorded below.

### Official ksnctf #39 distribution (2026-11-18)

Following the user's direction to use the official source, the official
[ksnctf #39 page](https://ksnctf.sweetduet.info/problem/39) was identified and
its linked `split_flag.php` and `flag.zip` were retrieved through the scoped
METIS web adapter. They are registered in run
`0045b063168045c289eaef276dab21c2`; the same-origin PHP fetch required no
credentials or external service grant. The PHP source states that the flag is
padded to avoid information leakage, creates six `random_bytes($n)` shares,
XORs them into a seventh share, and exits. Archive metadata confirms seven
encrypted, stored entries with the expected Info-ZIP header shape.

The bounded `infozip_seed` analysis matched the leaked first header byte for
all seven files and predicted the random bytes. These bytes are encrypted
twice by Info-ZIP, so this result is not known plaintext for the stored data.
A dummy-key decryption was rejected by its header check. No Stay key was
recovered, no independent Stay round-trip vector was validated, and no
candidate was sent to the official verifier. The archive is acquired, but
ksnctf #39 and the Stay acceptance gate remain unresolved. The primary
reference is [Stay's FSE paper](https://math.ucr.edu/~mike/zipattacks.pdf).
