# Pinned llama-server token-work bound audit

Source inspected: `ggml-org/llama.cpp` commit `b1b770d90`, especially `tools/server/server-context.cpp` and `src/llama-context.cpp`. This note concerns a possible bound on model-evaluated tokens, not reported completion usage.

The current METIS adapter starts one slot (`--parallel 1`), context size 4096, without context shift or warmup, and sends one `/completion` request with `cache_prompt=false` and bounded `n_predict`. It reserves `4096 + n_predict` after `/tokenize`. That amount cannot be promoted as a proven work cap:

- `server-context.cpp:3649-3668` repeats a batch when `decode()` returns false. `decode()` invokes `llama_process` at line 4717 and may halve its batch and retry at lines 4763-4770. A failed attempt is absent from the successful completion's `tokens_evaluated` / `tokens_predicted` fields (`server-task.cpp:340-341`).
- `llama-context.cpp:2140-2400` has its own memory-optimization retry and microbatch loop. `llama_context::decode` can dispatch to `encode` for a model without decoder memory (line 2143). The complete set of model-family and backend paths has not been reduced to a verified token-work accounting rule.
- A bound such as `4096 * (n_predict + 1)` is plausible but unproven here. It needs a formal bound on attempted batches, the work performed by each failed `llama_process`, and any re-evaluation across server transitions. Model load and startup must also be shown to make zero inference-token calls with `--no-warmup` for the pinned build.

Decision: leave `hard_cap_capable` and `hard_token_budget_enforced` false. Do not run a held-out study on this reservation as a hard token limit. A useful next step is instrumenting every `llama_process` and lower-level encode/decode attempt in the pinned binary, then using that trace to falsify a source-derived upper bound under prompt lengths at context edges, forced memory failures, timeouts, cancellation, and concurrent callers.
