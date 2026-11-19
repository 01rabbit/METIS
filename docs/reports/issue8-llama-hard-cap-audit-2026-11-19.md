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

The held-out protocol currently binds string `model_pin` and `runtime_pin`.
The specialist accepts a matching model ID, while its binary and model SHA-256
values and SQLite `budget_key`/`token_limit` are independent constructor
arguments. The real-model gate checks only the runner's Boolean capability.
Before enabling it, bind a verified runtime and model digest, shared budget
key, token ceiling, and exact database to the committed study and reject
every mismatch before a model turn is reserved. Ensure the runner identity
cannot be asserted merely by a subclass or mutable attribute.

Keep `LlamaServerBackend.hard_cap_capable` and
`LlamaSpecialist.hard_token_budget_enforced` false. The preregistered
real-model runner must continue to refuse this adapter. The existing
concurrency, cancellation, timeout, and permanent-reservation tests establish
those narrower behaviors; they do not establish strict token budgeting.
