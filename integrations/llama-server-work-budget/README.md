# Native llama-server token-work cap prototype

This builds a separate llama-server from upstream
[b1b770d90d94cad9e9ea5b993bdbc383a522fb28](https://github.com/ggml-org/llama.cpp/commit/b1b770d90d94cad9e9ea5b993bdbc383a522fb28).
The binary requires a positive process-wide token budget before llama-server
initializes. It serves one local decoder-only GGUF on a Unix socket with one
slot, a 4096-token context, and the built-in CPU backend. A trusted controller
provides the socket path, the write end of a pipe, and a fresh launch nonce.
The build disables external backend discovery and upstream argument merging
from system configuration, user configuration, and the environment. The
launcher rejects runtime environment overrides. The launch profile disables
warmup, context shift, multimodal loading, speculation, and the web UI.

The build requires Git, CMake, a native C/C++ toolchain, and Python 3.12 or
newer. The script checks Python before fetching or compiling.

```sh
scripts/build_llama_work_budget.sh /tmp/metis-llama-guard-build
```

## Launch and terminal receipt

The controller creates the socket's parent with mode `0700`. The launcher
requires a canonical absolute socket path ending in `.sock` under a directory
owned by the effective user. It rejects paths that already exist, including
stale sockets and symlinks. The dedicated argument parser preserves the
literal socket path and the listening code opens exactly one AF_UNIX socket.
Processes under the same operating system user share this trust boundary.
The controller must protect the directory and its ancestors against rename
or replacement for the lifetime of the process.

The controller inherits only the write end of a fresh pipe into the child,
closes its own copy after launch, and keeps the read end until the process has
exited. The launcher requires a write-only pipe descriptor greater than 2 and
marks the descriptor nonblocking and close-on-exec. The launch argument shape
is as follows.

```text
llama-server --metis-work-budget TOKENS --model LOCAL_GGUF --socket ABS_PATH.sock
             --metis-receipt-fd FD --metis-launch-nonce LOWERCASE_HEX32
```

Example terminal receipt for a successful shutdown after 22 charged positions
under a cap of 24.

```json
{"version":1,"nonce":"0123456789abcdef0123456789abcdef","cap":24,"charged":22,"reason":"shutdown"}
```

The binary seals the balance before writing a single newline-delimited
record of at most 256 bytes. The nonblocking pipe write is atomic. The
record contains the launch nonce, original cap, and number of charged
positions. Terminal reasons and expected process observations are:

| Reason | Process observation |
| --- | --- |
| `shutdown` | Normal server shutdown, status 0 |
| `server_error` | Server returned an error status |
| `cap_denied` | Pre-dispatch denial, status 75 |
| `unsupported_graph` | Pre-dispatch denial of an unmetered graph, status 75 |

A failed receipt write exits with status 74. An invalid launch, fatal runtime
failure, or SIGKILL can leave the pipe empty. A controller must wait for process
exit and require one matching record before accepting a result. Any absent,
truncated, duplicate, inconsistent, or mismatched receipt requires a failed
outcome with the full admission charge retained. The pinned upstream SIGTERM
handler acquires queue state directly. An in-flight SIGTERM can stall before
the receipt. The controller must bound its wait, kill and reap a stalled
process, and keep the full charge when the receipt is missing. Abrupt shutdown
can leave the socket path for the controller to clean up.

## Accounting boundary

The unit charged is a token position in a submitted model microbatch. Both
`llama_context::encode` and `llama_context::decode` call
`process_ubatch`, which passes `ubatch.n_tokens` to `graph_compute`.
The guard subtracts this count immediately before the scheduler call. The
atomic balance is initialized once and is shared across contexts and requests
for the lifetime of the process. A graph that returns an error keeps its
charge. A retry that submits another graph takes another charge. A retry that
fails before submission takes no charge. Model-load graph reserve and backend
buffer allocation are outside this token-work unit.

Denied submissions terminate the process before backend dispatch. That prevents
denial from being interpreted as a retriable decode error. The patch also
denies the known graph paths outside the microbatch unit in this source pin,
including KV shift, the two multimodal scheduler calls, and training. An
ordinary process restart creates a new balance. Cross-process budget ownership
belongs to the controller.

## Startup probe and smoke test

Upstream `tools/server/server-context.cpp` calls
`common_context_can_seq_rm` during model initialization. In
`common/common.cpp`, that function submits two token positions to
`llama_process` to test partial removal for the smoke fixture. It runs even
with `--no-warmup`.

Use the public upstream
[stories260K.gguf fixture](https://huggingface.co/ggml-org-dev/stories260K/blob/main/stories260K.gguf).
The smoke test verifies the fixture digest before launch.

```sh
python3 integrations/llama-server-work-budget/smoke.py \
    /tmp/metis-llama-guard-build/build/bin/llama-server /absolute/path/to/stories260K.gguf
```

The smoke test on macOS arm64 checks startup refusal at cap 1, prompt refusal
at cap 21, one completion at cap 22, and the next decode graph after 23 charged
positions. Cap 24 allows generation of three tokens, which submits two decode
graphs after the startup and prompt positions. Each terminal record is checked
against the exact cap, nonce, submitted work, and reason. Additional cases
cover a literal path containing commas and quotes, stale sockets and
symlinks, a nonprivate directory, a broken receipt pipe, a timed-out client
whose server is killed, and ambient config that tries to require an API key.

This builds on the native gate in METIS PR #87. Production qualification still
requires a trusted scheduler-to-admission binding, model and executable
registration for supported runtimes, immutable split-file identity, and tests
for alternate models, platforms, concurrent callers, and injected backend
failures. Completion usage remains distinct from submitted work.

## Controller qualification with the public fixture

The fixture-only Python boundary binds the admission to one staged binary,
the registered single-file stories260K GGUF, and the digest of the exact
request profile. It supports output allowances of one or three tokens. Before
launch it subtracts the entire allowance from the committed token amount and
requires the resulting native graph cap to be positive. This leaves room for
the last sampled token, which can be returned without entering another graph.

Before staging, the controller checks the manifest against an independently
supplied expected digest, checks the patch and current host target, and
matches the approved binary digest to the committed runtime pin. It stages
the executable and model in a private directory and verifies those copies
before claiming the launch. Directory isolation assumes a trusted controller
and operating system user.

After committing a unique claim, the controller uses the private Unix socket
for readiness, independent tokenization, and one completion request. It
requires the known 20 input token IDs, matching completion counters, and
the frozen limits, stop settings, and non-speculative generation settings.
The terminal record must match the launch nonce, the reduced graph cap, and
the observed process exit. Observed work in the ledger counts submitted
graph positions. The controller also checks that graph work plus sampled
outputs fit the original admission. An EOS or stop match can reduce the
observed output while the full requested headroom stays reserved.
All outcomes retain the entire admission charge. An abruptly terminated
controller may leave an orphaned process or a claim without an outcome. The
same claim cannot be reused, and the process retains its immutable native cap.

Run the optional real integration fixture against a build from the native patch.

```sh
METIS_NATIVE_FIXTURE_BINARY=/tmp/metis-llama-guard-build/build/bin/llama-server \
METIS_NATIVE_FIXTURE_MODEL=/absolute/path/to/stories260K.gguf \
METIS_NATIVE_FIXTURE_MANIFEST=/tmp/metis-llama-guard-build/native-build.json \
METIS_NATIVE_FIXTURE_PATCH=/tmp/metis-llama-guard-build/llama-server.patch \
METIS_NATIVE_FIXTURE_MANIFEST_SHA256="$approved_manifest_sha256" \
    .venv/bin/python -m pytest tests/test_native_work_fixture.py -k public_native_fixture
```

The registered digest identifies the complete single-file fixture. Other GGUF
files, including split layouts, fail staging before the process starts. The
controller has no general-purpose model or prompt API. Its deadline covers
readiness and the sole request, followed by bounded process shutdown and reap.
A missing or invalid receipt yields a failed observation and zero refund.


| Output allowance | Admission | Graph cap | Observed qualification with the public fixture |
| --- | --- | --- | --- |
| 1 | 23 | 22 | 22 graph positions and 1 sampled output |
| 3 | 27 | 24 | 24 graph positions and 3 sampled outputs |
| 3, fixed EOS or stop | 25 | 22 | 22 graph positions and 1 sampled output |

The first two cases fail to complete when the admission is one token smaller.
The stop and EOS profiles also deny work at admission 24. This qualification
depends on the fixed fixture and does not establish a general-provider token
ceiling. Trusted build and model registration and scheduler/protocol binding
are still required before enabling the METIS capability.

## Offline build identity

The build script also leaves `native-build.json` and the applied patch at
the top level of the build directory. The sidecar records the upstream
commit, patch and executable SHA-256 digests, the checked CMake options,
and the CMake-reported target and compiler. It contains observations from
the build and carries no independent approval.

Verify the sidecar by supplying the expected digest from separately reviewed
release evidence. A digest computed from the candidate sidecar itself only
checks the candidate against its own claims.

```python
from pathlib import Path

from metis.evaluation.native_build_identity import verify_native_build

root = Path("/tmp/metis-llama-guard-build")
identity = verify_native_build(
    root / "native-build.json",
    expected_manifest_sha256=approved_manifest_sha256,
    binary=root / "build/bin/llama-server",
    patch=root / "llama-server.patch",
    model=Path("/absolute/path/to/stories260K.gguf"),
    target_os="Darwin",
    target_arch="arm64",
)
```

The verifier opens bounded regular files to compare their bytes and accepts
the registered single-file public fixture. It launches no processes. These
checks rely on the independently approved digest and the build system's target
metadata. Production still needs trusted publication of that digest and equivalent
artifact binding beyond this fixed public fixture profile. Verification alone
supplies no evidence about the backend's runtime token accounting.
