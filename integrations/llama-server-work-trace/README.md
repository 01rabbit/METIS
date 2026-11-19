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

`graph_positions` counts positions passed to `graph_compute`; it does not count
GGML operations, backend kernel retries below that boundary, memory use, or
provider billing. The decoder-only public fixture does not exercise direct
multimodal graph paths or encoder-only models. This trace can reveal a counter
or source-path discrepancy in the observed profile, but it does not prove an
upper bound for all models or runtimes.

## Build

The builder checks out the exact source commit into a fresh directory, verifies
the commit, verifies the patch SHA-256
`7b4e755bd13a2cc2505fb6147dd066de682da2b6e1aa6ff9715b68238a62123d`, applies
the patch with normal context checks, and builds the CPU-only server. The
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
Supply the file locally; the trace runner does not download models.

## Run

The runner checks the model and binary digests against the manifest, starts a private Unix-socket server
with a minimal environment and no warmup/context shift, limits the server log
file to 4 MiB at the OS level, makes one fixed, answer-free completion request,
then stops the server and validates its single aggregate record. It accepts no
arbitrary prompt argument.

```sh
scripts/run_llama_work_trace.py \
    /tmp/metis-llama-trace-build/build/bin/llama-server \
    /path/to/stories260K.gguf
```

To exercise the server's batch-retry control-flow path, a test-only environment
switch injects one synthetic precompute refusal after readiness and before
graph submission. The probe requires exactly one injected refusal, one failed
process call, and one server retry, with no graph failure. The following attempt
runs normally:

```sh
scripts/run_llama_work_trace.py --inject-one-retry \
    /tmp/metis-llama-trace-build/build/bin/llama-server \
    /path/to/stories260K.gguf
```

This is a control-flow probe, not a real KV-capacity or allocator failure. A report can be
written once to a new 0600 file with `--output PATH`; existing output files are
never replaced. Output includes digests and aggregate counters only.

## Observed local probe

On Darwin arm64 with the pinned CPU build and the registered public fixture, a
single completion returned 20 evaluated and 3 predicted positions. The trace
recorded one startup `llama_process` call and 2 startup graph positions, then 3
request calls and 22 request graph positions. With the synthetic retry enabled,
the request counters recorded one failed process call, one server batch retry,
one injected precompute refusal, and the same 22 graph positions. These are
single-profile observations; the synthetic refusal performs no graph work, so
it does not model the work of a real failed backend attempt. The pinned patch
digest prevents a self-consistent but unrelated patch copy from being accepted
by the runner, while the manifest alone still cannot prove binary build
provenance.

No context-edge, genuine allocator failure, timeout/cancellation, concurrent
caller, encoder, multimodal, alternate-model, or held-out comparison is
established by these two probes. They do not demonstrate a token ceiling,
provider cost bound, CTF solve, Issue #8 acceptance, or MUNIN benefit.
