# Issue #8 Ollama study integration gate

`metis agent ollama` now requires a fully validated held-out protocol, its
externally recorded SHA-256, and an externally recorded runtime-profile SHA-256.
The gate checks the run binding against its task, repetition, arm, treatment,
model, and budget. The protocol validator requires equal aggregate budgets
across every arm. A study-level SQLite record prevents later arms from using
another runtime profile. The prior exploratory protocol is explicitly closed.

The runtime profile covers the Ollama version, model manifest and GGUF hashes,
tokenizer binary hash, context length, output allowance, temperature, and seed.
This is a reproducibility condition, not a solution to mutable tag dispatch.
The current `OllamaSpecialist` advertises no hard-cap capability, and the new
gate therefore rejects all real-model held-out calls **before autopilot or a
model request**. The tests exercise protocol checks with a synthetic capability
override but also verify that the real default refuses all four arms.

No new protocol, CTF trial, model comparison, or official submission is created
by this change. An immutable or exclusively controlled model route and an
independent review are required before changing the capability flag.

## Dedicated-process feasibility check

On Ollama 0.40.16, a separate `ollama serve` process with a private empty
`OLLAMA_MODELS` directory and a random `127.0.0.1` port started successfully;
its `/api/tags` response contained zero models. A separate unauthenticated
HTTP request reached its `/api/delete` endpoint and received 404 for a
nonexistent tag. This made no change to the shared server or models. A probe
with `OLLAMA_HOST=unix://...` did not produce a Unix socket. Ollama's
[environment configuration](https://github.com/ollama/ollama/blob/main/envconfig/config.go)
parses `OLLAMA_HOST` as an IP/port address and documents `OLLAMA_MODELS` as
the model-directory selector.

A private directory and random loopback port isolate this process from the
ordinary Ollama instance, but the local HTTP API remains reachable by another
local process. They therefore do not eliminate tag mutation between the
pre-count and model request. A process supervisor would take roughly 1–2 days
to implement and test, with further platform-specific access isolation still
needed. We leave the hard-cap gate closed instead of treating a private port
as exclusive control.
