# Issue #8 direct llama.cpp hard-cap feasibility

This branch adds an answer-free local probe. It does not enable real-model held-out
execution or advertise `hard_token_budget_enforced`. No API key or Docker is needed.

The installed Homebrew `llama-cli` 1.0.0 (build 12359, `b1b770d90`) accepts
`--predict 1` and a local GGUF path. A direct invocation against the installed
Shisa 3B GGUF succeeded, but showed an interactive chat wrapper (`available
commands`, `/read`, `/glob`, and `> Hello`) and no machine-readable prompt or
generation token counts, even with `--single-turn --log-jsonl --verbose-prompt`.
The installed Qwen3.5 0.8B GGUF failed to load because this llama.cpp build
expected four `qwen35.rope.dimension_sections` entries and found three.

The direct CLI route therefore cannot presently establish that the separately
counted raw prompt is the prompt actually consumed by the model. It also cannot
reconcile actual usage after the call. The probe fails closed on both conditions.
It hashes the model, CLI and tokenizer, tests one harmless one-token prompt,
and emits only hashes, counts and capability booleans. It never records a model
response or challenge data.

Before a hard-cap capability can be enabled, use a controlled raw completion
route with an exact pinned model and engine binary, demonstrate tokenizer parity
for every supported prompt class, enforce a positive output-token maximum,
atomically reserve the input count plus that maximum in the shared SQLite run
ledger before invocation, retain the full reservation on timeout or crash, and
invalidate the run on missing or mismatched usage. A local peer able to mutate
the model, engine, or endpoint between the checks and dispatch remains outside
the guarantee unless access is genuinely isolated. A private loopback port or
file hash check alone does not remove that race.

Probe invocation from the repository worktree, with a separately chosen local
GGUF path and explicit installed binaries:

```sh
PYTHONPATH=src python3 -c 'import json,sys; from pathlib import Path; from metis.evaluation.llama_cli_cap_probe import probe; print(json.dumps(probe(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])), sort_keys=True))' \
  /path/to/model.gguf /opt/homebrew/bin/llama-cli /opt/homebrew/bin/llama-tokenize
```
