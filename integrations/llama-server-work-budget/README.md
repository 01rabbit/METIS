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

```sh
scripts/build_llama_work_budget.sh /tmp/metis-llama-guard-build
```

## Launch and terminal receipt

The controller creates the socket's parent with mode `0700`. The launcher
requires a canonical absolute socket path ending in `.sock` under a directory
owned by the effective user. It rejects a path that already exists. Processes
under the same operating system user share this trust boundary.

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
outcome with the full admission charge retained. Abrupt shutdown can leave the
socket path for the controller to clean up.

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
cover an existing socket path, a nonprivate directory, a broken receipt pipe,
a timed-out client whose server is killed, and ambient config that tries to
require an API key.

This stacks on the native gate in METIS PR #87. The Python admission ledger
still needs to claim each launch exactly once and record the outcome. Enabling
METIS capability also requires immutable executable and model identity including
split files, deadlines and cleanup owned by the controller, and qualification
for alternate models, platforms, concurrent callers, and injected backend
failures. Completion usage remains distinct from submitted work.
