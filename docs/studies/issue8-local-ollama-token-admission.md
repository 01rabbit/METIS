# Issue #8 local Ollama token admission prototype

This change adds a **conditional** local-model route for a bound real-model
held-out run. It does not launch or score a CTF trial. The existing Codex CLI
route still refuses a real-model held-out call without a hard token cap.

The route requires the caller to pin the Ollama manifest SHA-256, its GGUF model
layer SHA-256, and the `llama-tokenize` binary SHA-256. It checks the manifest
to GGUF relationship and compares the local `/api/tags` digest before each
call. It sends only raw text to `/api/generate`, sets a positive `num_predict`,
and refuses prompts whose token count plus output allowance exceeds `num_ctx`.
SQLite reservations, protected by the run lock and `BEGIN IMMEDIATE`, charge
input count plus maximum output before dispatch. Completed calls refund only
the difference between that reservation and reported usage. A crash leaves its
full reservation charged. Missing or mismatched usage marks the run invalid and
blocks later reservations. The ledger retains reported counts even on a
mismatch.

## Local compatibility observations

On Ollama 0.40.16 and Homebrew `llama-tokenize` 1.0.0 (build 12359,
`b1b770d90`), the GGUF tokenizer count equaled Ollama's `prompt_eval_count`
for raw, tool-free prompts:

| Model | Prompt class | Pre-count / reported input |
| --- | --- | ---: |
| `qwen3.5:0.8b` | ASCII, Japanese, special-token-like text, whitespace with emoji, 3,000-byte ASCII | 3/3, 4/4, 5/5, 7/7, 375/375 |
| `gemma4:12b` | ASCII, Japanese, special-token-like text | 4/4, 5/5, 16/16 |
| `gemma4:26b` | ASCII | 4/4 |
| `gemma4:12b` | JSON-schema constrained raw request | 15/15 |

The JSON-schema request produced 38 output tokens under a 128-token
`num_predict` limit. These probes were harmless and answer-free. The 12B model
is a practical local candidate for later evaluation, but its problem-solving
quality has not been measured by this change.

## Remaining gate

This is a reviewable mechanism, not permission to start a new study. The model
tag and local files can be changed by another process between verification
and use. The cap assumes a trusted local Ollama installation and stable pinned
files during each request. A model swap or server behavior change after the
pre-check can only be detected by the post-call count, after tokens are spent.
On this Ollama 0.40.16 installation, `/api/generate` did not accept a manifest
digest as `model`: a bare digest and `sha256:` prefix returned HTTP 404, while
`gemma4:12b@sha256:<digest>` returned HTTP 400. The request must use a mutable
tag. Thus this is **not** a hard cap against a concurrent local process that
changes the tag, files, or Ollama server. Its hard-cap claim is limited to the
trusted, stable local runtime and the pinned raw-text model path tested here.
Independent review and CI are required before this route can be considered for
a newly preregistered comparison. A subsequent study must still establish the
actual arm, oracle, runtime, and model-quality requirements separately.
