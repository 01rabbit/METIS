# Issue #8 pinned llama.cpp work trace

## Scope

This test-only CPU build traces llama.cpp source commit
`b1b770d90d94cad9e9ea5b993bdbc383a522fb28` against the public
`stories260K.gguf` fixture (SHA-256
`270cba1bd5109f42d03350f60406024560464db173c0e387d91f0426d3bd256d`).
It records aggregate `llama_process`, encode/decode, graph-dispatch, memory
prepare, retry, and failure counters. Prompts, generated text, and raw process
logs are not retained.

The fixture is the public `ggml-org-dev/stories260K` artifact: https://huggingface.co/ggml-org-dev/stories260K/blob/main/stories260K.gguf.

The instrumented patch SHA-256 is
`c97500f6a98a2c34554953f82eb46ce6b39d1b82581fa1aef65b197090dd1c4c`.
A fresh build from the pinned commit produced binary SHA-256
`dc1baf03d86236e1aa187bd53e9e404abe4e0c6b0119f4addd2e72c629984065`.
The manifest records source, patch, binary, and host digests but is not a signed
or independent build attestation.

## Observed probes

On Darwin arm64, the normal fixed request returned HTTP 200 with 20 evaluated
and 3 predicted positions. Startup recorded one process call and 2 graph
positions. The request recorded 3 process calls, 3 graph dispatches, and 22
graph positions, with no memory prepare failure.

With the test-only memory prepare status injection, the fixed request returned
HTTP 200 with the same usage counts. The request trace recorded one injected
`FAILED_PREPARE`, one memory-update optimization attempt, and one `false` return
from `memory_update(true)`. That boolean does not distinguish `NO_UPDATE` from
an optimization failure. The server then made one batch retry: 4 process calls
total, one failed process call, and 3 successful graph dispatches covering 22
positions. This executes the pinned memory-update and server retry branches;
the injected status is synthetic and is not evidence of an actual allocator or
KV-capacity failure.

An exploratory one-off harness made two context-edge requests with 4,095 and
4,088 prompt tokens, each with an eight-token prediction allowance. Both
received HTTP 400 before any `llama_process` call and recorded zero process
calls and graph work. For the 4,088-token request, response metadata was
`exceed_context_size_error`, `n_ctx=2048`, and `n_prompt_tokens=4088`, despite
launching the server with `--ctx-size 4096`. The reason for this effective
context mismatch was not investigated. The one-off harness and prompt text were
not retained, so these observations are exploratory and cannot be reproduced
with the committed runner.

## Validation

- `scripts/build_llama_work_trace.sh /tmp/metis-issue8-context-boundary-final-v5`
  completed from a fresh pinned-source checkout; binary SHA-256 was
  `dc1baf03d86236e1aa187bd53e9e404abe4e0c6b0119f4addd2e72c629984065`.
- Normal and injected-memory-prepare requests completed and parsed against the
  aggregate trace schema.
- `PYTHONPATH=.:src pytest -q tests/test_native_work_trace.py`: 37 passed;
  the primary checkout virtualenv was used for this worktree.
- Ruff, mypy, `scripts/check_repo.py` (zero findings), shell syntax validation,
  and `git diff --check` passed after the final patch update.

## Limits

The injected status is not a genuine memory failure. The context-edge requests
were rejected before inference. This is one public fixture and one Darwin arm64
profile; timeout/cancellation, concurrent calls, encoder or multimodal models,
other backends/models, held-out benchmarks, and actual allocator exhaustion
remain untested. The trace does not establish a strict token/work ceiling,
provider cost limit, CTF solve, MUNIN benefit, or any Issue #8 acceptance
criterion. `hard_cap_capable` and `hard_token_budget_enforced` remain false. No
official challenge endpoint or verifier was contacted.
