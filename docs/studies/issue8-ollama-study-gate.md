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
