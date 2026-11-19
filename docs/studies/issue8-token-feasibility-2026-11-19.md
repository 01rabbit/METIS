# Issue #8 pre-dispatch token-cap feasibility, 2026-11-19

This investigation used only harmless model prompts. No CTF candidate, private
oracle, held-out challenge, or credential was sent. It evaluates whether the
current no-new-key model routes can prove a token ceiling *before* a specialist
call. PR #60 remains the fail-closed gate for real-model held-out execution.

## Codex CLI 0.169.0

With `codex exec --ignore-user-config --strict-config`, each proposed output
limit key was rejected before execution as an unknown configuration field:

- `output_token_limit=16`
- `model_max_output_tokens=16`
- `max_output_tokens=16`

`model_context_window=128` was accepted, but a tool-less `gpt-6.2-sol` prompt
requesting the single-word reply `OK` reported 15,545 input tokens and five
output tokens. This setting therefore cannot be used as an input-token cap.
The CLI's usage is returned after completion. These observations do not prove
that every possible Codex setting lacks a limit; they rule out the tested keys
and the context-window setting as a proven cap for this runtime.

## Local Ollama 0.40.16

The local installation has models including `qwen3.5:0.8b`, `qwen3.5:2b`,
and `gemma4:12b`. The following calls used `qwen3.5:0.8b` on loopback via
`/api/generate`, `raw=true`, and no tools:

| Prompt | Options | Reported prompt tokens | Reported output tokens |
| --- | --- | ---: | ---: |
| `Reply OK.` (9 bytes) | `num_ctx=128`, `num_predict=8` | 3 | 8 |
| 3,000 ASCII `x` bytes | `num_ctx=128`, `num_predict=8` | 375 | 8 |
| `Count only.` | `num_ctx=128`, `num_predict=0` | 3 | 2,045 |

`num_ctx` did not bound the input-token charge. A positive `num_predict` limited
the two observed output counts, while zero did not mean zero output. The tested
local server returned 404 for `/api/tokenize`; no model-specific local
tokenizer library is installed. Prompt-byte limits alone have no verified
token-count bound for this tokenizer. A conservative estimate based on bytes
would be a hypothesis, not evidence of a strict cap.

`ollama show qwen3.5:0.8b --verbose` reports architecture `qwen35`, tokenizer
model `gpt2`, and tokenizer pre-processing `qwen35`. Those metadata do not expose
an exact token-count function. The installed Ollama CLI also offers no public
tokenization command. We found no compatible `llama-tokenize` executable or
local `gguf`, `llama_cpp`, `tokenizers`, `sentencepiece`, or `transformers` Python
module. Until a pinned implementation is compared with the server's
`prompt_eval_count` on representative raw prompts, including Unicode and
special-token-like strings, no exact pre-dispatch admission check is established.

## Decision

No tested no-new-key route proves both input and output bounds before a call.
Do not claim a hard shared token cap from these observations. Keep new
real-model comparisons blocked. Before a new preregistration, an authorized
runner must expose a verified model-specific input-token count or hard input
admission, a positive output-token limit, and atomic per-run reservations
across parallel specialists. Its tests must cover retries, cancellation,
unknown usage, and service responses exceeding the declared bound.

After this first probe, the user provided `/Users/mao/.local/bin/ai-claude`.
An independent, tool-less review through that launcher suggested a byte-count
upper bound for verified byte-level tokenizers, with explicit overhead and a
positive `num_predict`. The reviewer marked this as an unverified inference and
identified model changes, hidden templates, context shifting, and concurrent
reservations as failure conditions. We therefore did not turn that suggestion
into a hard-cap claim. The plain `claude` executable was not used.
