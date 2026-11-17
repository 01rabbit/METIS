# Issue #6 candidate/report handoff diagnostic preregistration (2026-11-18)

## Question and scope

Does allowing a specialist to store its private candidate and submit its compact report in the same Codex turn improve workflow-complete correctness under the existing eight-call budget? Does that effect account for the earlier multi-specialist underperformance?

This is a new prospective diagnostic. It will not reuse or rerun any task or record from the symmetric replication. It can test the handoff mechanism on bounded synthetic encoding tasks; it cannot establish broad CTF or AlpacaHack performance. The original negative symmetric result remains unchanged.

## Frozen design

- **Runtime:** Codex CLI `0.169.0`, `gpt-6.1-sol`, reasoning effort `low`; memory retrieval disabled. Abort before model calls on a version mismatch.
- **Tasks:** 30 newly seeded task clusters: all 15 unordered pairs from Base64, Base32, hex, Base85, Base64URL and percent encoding, with two fresh task instances per pair. Each task has two independently generated 12-byte printable components. One trial per cluster; no outcome-based extension.
- **Arms, randomized independently within each task:**
  - `single`: one specialist receives both artifacts, with an eight-turn assignment cap and an eight-call run cap; combined candidate/report is allowed.
  - `multi_separate`: two concurrent specialists receive one artifact each, each with a four-turn cap under the shared eight-call cap; the controller disables combined candidate/report and requires the legacy separate handoff.
  - `multi_combined`: identical assignments, four-turn per-specialist caps, eight-call run cap and tools; combined candidate/report is allowed and encouraged when both are ready.
- **Fairness:** All arms use identical artifact generation, four mediated actions, two global slots, 600-second wall limit, pinned model/CLI, protected final composition, and private oracle. The component-to-specialist assignment is counterbalanced by a seeded per-task swap. Failed, incomplete, invalid, or timed-out workflows score zero.
- **Primary contrast:** `multi_combined` minus `single` on workflow-complete, oracle-verified tasks. The 30 paired task IDs are the resampling clusters. A measured gain requires the paired 95% task-cluster bootstrap interval to be entirely above zero; a faster incomplete run is not a gain.
- **Mechanism contrast:** `multi_combined` minus `multi_separate` on workflow completion and correctness. This isolates the option to combine candidate/report within the two-specialist architecture at the same total and per-assignment call caps. It does not by itself prove the historical failure was caused by call starvation: prompt timing and recovery behavior are part of this handoff treatment.
- **Retained metrics:** Answer-free per-arm booleans and counts only: protected-oracle result, synthesis/job states, elapsed seconds, observed/reserved calls, mediated actions, reported token counters, candidate-ready jobs at termination, decision-action counts, report-rejection count, and model-turn budget denials. Do not retain component bytes, plaintext, candidates, candidate paths, final digests, oracle contents, or raw model messages. Usage and cost remain `unknown` if unavailable.
- **Analysis:** Paired task-level differences for both declared contrasts; 10,000 deterministic bootstrap resamples of the 30 task clusters. Report protocol-complete oracle solves, protocol completion, all discordant outcomes, call/action use, latency, tokens, call-ceiling failures with a candidate already ready, and report rejection counts. Latency is secondary because fast failures can lower the mean.
- **Safety and cleanup:** All challenge inputs are generated locally for this diagnostic. The protected oracle and temporary artifacts live outside the repository and are deleted on normal exit; retained JSON is answer-free and written atomically after each completed arm. No external challenge or service is contacted and no candidate is submitted.

## Interpretation rule

The diagnostic can support a narrow gain claim only if `multi_combined` beats `single` on the primary paired workflow-complete oracle outcome under the declared interval rule. The handoff mechanism is supported only if `multi_combined` also reduces handoff-related calls and candidate-ready call-ceiling failures versus `multi_separate`, without offsetting report rejection or correctness failures. Otherwise report the result as inconclusive or negative and keep Issue #6 open. The study does not independently complete Issue #6's review/merge gate or Issue #7's dependency.
