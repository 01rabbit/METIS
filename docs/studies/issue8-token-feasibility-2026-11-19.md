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

## Decision

No tested no-new-key route proves both input and output bounds before a call.
Do not claim a hard shared token cap from these observations. Keep new
real-model comparisons blocked. Before a new preregistration, an authorized
runner must expose a verified model-specific input-token count or hard input
admission, a positive output-token limit, and atomic per-run reservations
across parallel specialists. Its tests must cover retries, cancellation,
unknown usage, and service responses exceeding the declared bound.

The requested `ai-claude` launcher was not present on this host's PATH or in
the searched local configuration. The plain `claude` executable was not used.
