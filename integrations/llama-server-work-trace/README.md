# Test-only llama.cpp work trace

This integration records aggregate execution counters from the pinned
llama.cpp commit `b1b770d90d94cad9e9ea5b993bdbc383a522fb28`. It is a separate
instrumented build and does not enable or claim a strict token budget. METIS's
`hard_token_budget_enforced` and held-out eligibility remain false.

The trace records startup and request phases separately. It counts
`llama_process` calls by encode/decode type, their input positions and failures,
`llama_context::encode`/`decode` invocations, graph dispatches and positions,
pre-dispatch failures, graph failures, zero-position graph calls, and server
batch retries. The record contains only counts, a build pin, and a one-run
nonce. It never records prompts, generated text, tokens, or model output. The
runner discards raw server logs when its temporary directory is removed.
It also counts memory-prepare failures and the associated memory-update retry
attempts and outcomes.

`graph_positions` counts positions passed to `graph_compute`; it does not count
GGML operations, backend kernel retries below that boundary, memory use, or
provider billing. The decoder-only public fixture does not exercise direct
multimodal graph paths or encoder-only models. This trace can reveal a counter
or source-path discrepancy in the observed profile, but it does not prove an
upper bound for all models or runtimes.

## Build

The builder checks out the exact source commit into a fresh directory, verifies
the commit, then checks this patch SHA-256 before applying it:
`c97500f6a98a2c34554953f82eb46ce6b39d1b82581fa1aef65b197090dd1c4c`. It
applies the patch with normal context checks and builds the CPU-only server. The
runner also rejects any build manifest whose patch digest differs from this
repository-pinned digest. The manifest is a content-addressed build record,
not a signed attestation that independently proves how a supplied binary was
built. The trace binary is not an approved runtime build and cannot pass the
native held-out build identity gate.

```sh
scripts/build_llama_work_trace.sh /tmp/metis-llama-trace-build
```

For an offline reproduction, `METIS_LLAMA_SOURCE_REMOTE` may point to a local
Git mirror that contains the pinned commit. `METIS_LLAMA_BUILD_JOBS` accepts
1–32 and defaults to 4. The builder refuses to reuse an existing build
directory.

The only accepted model fixture is the public `stories260K.gguf` file with
SHA-256
`270cba1bd5109f42d03350f60406024560464db173c0e387d91f0426d3bd256d`.
It is available from [the ggml-org-dev Hugging Face fixture](https://huggingface.co/ggml-org-dev/stories260K/blob/main/stories260K.gguf).
Supply the file locally; the trace runner does not download models.

## Run

The runner checks the binary digest against the build manifest and the model
digest against the public fixture pin. It starts a private Unix-socket server
with a minimal environment and no warmup/context shift, limits the server log
file to 4 MiB at the OS level, makes one fixed, answer-free completion request,
then stops the server and validates its single aggregate record. It accepts no
arbitrary prompt argument. Hashing and later execution/model loading use paths,
so a concurrent same-user replacement between those steps is outside this
probe's protection. The build disables llama.cpp subprocess support; shutdown
signals the server process group and reaps the server process. On SIGTERM the
runner stops the server, removes the private socket and log, and exits with 143.

```sh
uv run --locked --extra dev python scripts/run_llama_work_trace.py \
    /tmp/metis-llama-trace-build/build/bin/llama-server \
    /path/to/stories260K.gguf
```

To exercise the memory-prepare recovery path, a test-only environment switch
overrides one `init_batch` status only when the pinned code reports `SUCCESS`,
changing it to `FAILED_PREPARE` after readiness. The real
`memory_update(true)` branch then runs. Depending on its boolean result, the trace must show exactly one
internal retry, or one `false` result followed by one server batch retry; all
other combinations are rejected. A `false` result does not distinguish
`NO_UPDATE` from a failed optimization. This is injected status, not a genuine
allocator or KV-capacity failure. Both modes require a successful request
process call and a graph dispatch with positive positions. Startup must have no
failed process, retry, memory-prepare failure, or graph failure:

```sh
uv run --locked --extra dev python scripts/run_llama_work_trace.py --inject-one-retry \
    /tmp/metis-llama-trace-build/build/bin/llama-server \
    /path/to/stories260K.gguf
```

This is a control-flow probe, not a real KV-capacity or allocator failure. A
report can be written once to a new 0600 file with `--output PATH`; existing
output files are never replaced. Output includes digests and aggregate counters
only.

## Observed local probes

On Darwin arm64 with the pinned CPU build and registered public fixture, the
normal request returned HTTP 200 with 20 evaluated and 3 predicted positions.
Startup recorded one process call and 2 graph positions. The request recorded 3
process calls, 3 graph dispatches, and 22 graph positions, with no memory
prepare failures.

With the synthetic memory-prepare status injection, the same request returned
HTTP 200 with the same usage counts. The request trace recorded one injected
`FAILED_PREPARE`, one memory-update attempt, and one `false` return from
`memory_update(true)`. This does not distinguish `NO_UPDATE` from an
optimization failure. The server then made one batch retry: 4 process calls total, one
failed process call, and 3 successful graph dispatches covering 22 positions.
This exercises the pinned memory-update and server-retry branches, but the
failure status is injected; it is not evidence of a real allocator or KV-cache
failure.

An exploratory one-off harness made two context-edge requests (4,095 and
4,088 prompt tokens, each with an 8-token prediction allowance). Both returned
HTTP 400 before any `llama_process` call; traces contained zero process calls
and zero graph work. For the 4,088-token request, the response error metadata
was `exceed_context_size_error`, with `n_ctx=2048` and
`n_prompt_tokens=4088`, despite the server being launched with `--ctx-size
4096`. The reason for that effective-context mismatch was not investigated.
The one-off harness and prompt text were not retained, so these observations
are exploratory and are not reproducible from the committed runner.

The field `injected_memory_prepare_failures` explicitly labels the synthetic
status injection. The pinned patch digest prevents a self-consistent but unrelated patch copy
from being accepted by the runner, while the manifest alone still cannot prove
binary build provenance. No genuine allocator failure, timeout/cancellation,
concurrent caller, encoder, multimodal, alternate-model, or held-out comparison
is established. These probes do not demonstrate a token ceiling, provider cost
bound, CTF solve, Issue #8 acceptance, or MUNIN benefit.
