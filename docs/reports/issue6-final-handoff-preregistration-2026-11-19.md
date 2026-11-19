# Issue #6 final-call handoff diagnostic preregistration (2026-11-19)

## Question

Does reserving each multi specialist's fourth and final model call for a compact report or a combined private candidate and report improve workflow-complete, protected-oracle-verified correctness? This is a fresh synthetic diagnostic. The previous negative result remains unchanged.

## Frozen design before model calls

- Use `scripts/run_issue6_handoff_diagnostic.py --final-handoff-diagnostic`. The default switch-off path retains the 2026-11-18 study. The new path refuses to overwrite `docs/reports/data/issue6-final-handoff-diagnostic-2026-11-19.json`.
- Use seed 20261120 and its derived order seed. Generate 30 new task clusters: 15 encoding pairs, two instances per pair, one repetition. Do not inspect answers during specialist work or add outcome-driven tasks.
- Randomize three arms within each cluster: `single` (one specialist, both artifacts, current combined handoff), `multi_combined` (two specialists, current combined handoff), and `multi_final_handoff` (same two assignments; each fourth call uses a strict schema with only `candidate_report`, `report`, and `fail`).
- Hold model, CLI, reasoning effort, artifact generation, action cap, shared eight-call cap, two slots, 600-second wall limit, private oracle, and final digest composition identical to the prior diagnostic. Each multi specialist retains its four-call maximum. The final-call schema applies only to the new arm. A rejected final report consumes that call and fails the assignment; cancellation stops further calls.
- Retain only answer-free metrics: oracle and workflow booleans, states, calls, actions, time, usage counters, rejection counts, and budget denials. Never persist components, candidates, digests, oracle contents, or raw model messages. Temporary artifacts and oracle stay outside the repository.

## Outcomes and interpretation

The primary Issue #6 contrast is `multi_final_handoff` minus `single` on workflow-complete and oracle-verified tasks. Treat the 30 task IDs as paired clusters and use 10,000 deterministic bootstrap resamples. Issue #6's measured-gain condition passes only if the paired 95% interval is wholly above zero. Compare `multi_final_handoff` with `multi_combined` for the narrower handoff mechanism, reporting discordant pairs, raw oracle correctness, report rejections, call-ceiling failures with candidates ready, calls, tokens, and latency. Fewer calls or better workflow completion alone do not satisfy Issue #6. The synthetic study does not establish broad CTF performance or itself complete review and merge gates.

Do not claim an outcome from this preregistration. Real-model execution is separately scheduled after reviewing this change.
