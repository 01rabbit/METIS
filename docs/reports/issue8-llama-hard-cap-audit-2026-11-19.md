# Issue #8: llama-server hard token cap audit (2026-11-19)

Scope: PR #77 at `a44cc15`, a trusted local operator, pinned binary and GGUF,
Unix socket, no model tools. No CTF task or held-out comparison was run.

## Finding

`LlamaServerBackend` atomically reserves `/tokenize` prompt count plus the
requested maximum output in shared SQLite before `/completion`. Failed or
interrupted completions retain the whole charge. This is useful accounting,
but it is not yet a strict upper bound on actual model tokens. The server's
`tokens_evaluated` is checked only after inference. If it exceeds the prior
`/tokenize` result, the adapter fails closed for the *result* but the model
has already used the extra tokens. The new disagreement regression test
demonstrates precisely that timing. A single observed 12-token parity probe
does not establish parity for all prompts, special tokens, UTF-8 text,
long-context truncation, and runtime versions.

An opt-in `context_reservation` mode now reserves the complete configured
4096-token context plus `n_predict` before every inference, and the process
explicitly starts with `--no-context-shift`. Synthetic tests show that a
completion evaluating 100 tokens after `/tokenize` returned two fits this
reservation, and two concurrent backends cannot both spend a one-call cap.
This is a more conservative execution primitive. To promote it to a proven
strict cap, a pinned real runtime must show that context re-evaluation and
any internal prompt replay cannot make its count exceed the 4096-token
reservation. The cap needs an explicit mapping to the study budget.

A local smoke run used the Homebrew `llama-server` 1.0.0 executable and the
specified 1.9 GB Shisa GGUF, both SHA-256 checked at startup. With
`context_reservation=True`, `n_predict=2`, and a shared 16,392-token cap,
the ASCII, Japanese, and special-token-like prompts returned input/output
counts of 4/2, 11/2, and 14/2. All three calls completed. This checks only
those short prompt classes and this local binary; it is not a proof of the
worst-case context accounting semantics.

Startup is now explicitly `--no-warmup`, and the child receives a fixed
minimal environment instead of inherited `LLAMA_ARG_*`, proxy, or draft-model
settings. Before `complete()` reserves tokens the only request is `/health`;
the adapter sends neither a prompt nor a completion request. Any runtime
internal startup inference remains unmeasured, including with `--no-warmup`.
Tests verify injected environment does not reach the child and a fake server
exiting before a prompt creates no SQLite reservation; they do not measure
actual startup model-token use.
After this hardening, one answer-free local smoke call with the pinned
Homebrew binary and Shisa GGUF started successfully with `--no-warmup` and the
sanitized child environment. The harmless `Hello world.` prompt reported four
input tokens and two output tokens against a pre-call reservation of 4098.
No CTF or held-out task was involved.

The held-out protocol currently binds string `model_pin` and `runtime_pin`.
It now also accepts an optional committed `llama_backend` pin: binary and model
SHA-256, canonical state database path, shared budget key and ceiling, maximum
output, and conservative reservation mode. `bind_run` carries that pin into the
run binding. `run_assignment` compares it with the concrete `LlamaSpecialist`
configuration before reserving any model turn, and rejects every field mismatch.
Tests exercise the mismatches and confirm no turn reservation. This is a
preparatory binding, not a capability grant: the separate Boolean gate still
refuses real-model held-out calls. Before enabling that gate, verify the
runtime's actual token accounting and ensure capability cannot be asserted by
an arbitrary runner or mutable attribute.

Keep `LlamaServerBackend.hard_cap_capable` and
`LlamaSpecialist.hard_token_budget_enforced` false. The preregistered
real-model runner must continue to refuse this adapter. The existing
concurrency, cancellation, timeout, and permanent-reservation tests establish
those narrower behaviors; they do not establish strict token budgeting.
