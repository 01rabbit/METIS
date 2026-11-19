# Native llama-server token-work cap prototype

This builds a separate llama-server from upstream
[b1b770d90d94cad9e9ea5b993bdbc383a522fb28](https://github.com/ggml-org/llama.cpp/commit/b1b770d90d94cad9e9ea5b993bdbc383a522fb28).
The binary requires a positive process-wide token budget before llama-server
initializes. It serves one local decoder-only GGUF on loopback with one slot,
a 4096-token context, and the built-in CPU backend. Startup accepts only a
budget, a model path, and a port. The build disables external backend discovery
and upstream argument merging from system configuration, user configuration,
and the environment. The launcher rejects runtime environment overrides.
The launch profile disables warmup, context shift, multimodal loading,
speculation, and the web UI.

```sh
scripts/build_llama_work_budget.sh /tmp/metis-llama-guard-build
/tmp/metis-llama-guard-build/build/bin/llama-server \
    --metis-work-budget 4096 --model /absolute/path/to/model.gguf --port 8080
```

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

Denied submissions terminate the process with exit status 75 before backend
dispatch. That prevents denial from being interpreted as a retriable decode
error. The patch also denies the known graph paths outside the microbatch unit
in this source pin, including KV shift, the two multimodal scheduler calls, and
training. An ordinary process restart creates a new balance. Cross-process
budget ownership belongs to the caller.

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

With the pinned source and fixture on macOS arm64, a cap of 1 exited during
startup with `METIS token work budget denied, requested=2` before model
readiness. A cap of 22 allowed startup and a 20-position prompt with a
single generated token. An uncached repeat in the same process exited with
75. A fresh process with cap 21 became ready and exited with 75 when it tried
that prompt. The exact-cap case called `/tokenize` before completion.
With three generated tokens, cap 24 completed and cap 23 exited with 75
before submitting the last one-position decode graph.

The smoke server runs with a temporary upstream user configuration that
would require an API key if loaded. Both tokenization and completion succeed
without credentials.

This prototype is separate from METIS capability detection. Enabling a runtime
requires controller-owned launch and termination, immutable executable and
model identity, a reservation spanning startup and every owned process, and
durable outcomes on rejection, timeout, and cancellation. Alternate models
and platforms, injected backend failures, and concurrent HTTP clients still
need qualification. Completion usage remains distinct from submitted work.
