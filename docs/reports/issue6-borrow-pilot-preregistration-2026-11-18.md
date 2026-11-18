# Issue #6 dynamic-borrowing feasibility pilot: frozen design

This is a prospective synthetic feasibility pilot, not P5 acceptance. It tests
whether opt-in shared-turn borrowing improves workflow-complete verified outcomes
under the existing total call cap. Earlier negative studies remain unchanged.

- Study ID `issue6-borrow-pilot-2026-11-18`, seed `2026111807`, arm-order seed
  `2026111807 XOR 0x6A09E667`. Output
  `docs/reports/data/issue6-borrow-pilot-2026-11-18.json` must not exist at
  launch. Task IDs `borrow6-00` through `borrow6-05` are new.
- Six clusters, two each of Base64/Base32, Base64/hex and Base64/Base85. Each
  task has two independent printable 12-byte components; one trial per cluster.
  Every arm receives the same task and controller-side SHA-256 composition and
  protected local oracle. Specialist reports never contain decoded components.
- Three arms per cluster in seeded random order: `single` (one specialist,
  eight-turn assignment), `multi_fixed` (two specialists, four turns each), and
  `multi_borrow` (two specialists, `dynamic_borrowing=True`). The multi arms
  have identical artifact scopes and `candidate_report` instructions. Every
  arm has eight total model calls, four mediated actions, two slots and 600 s.
- Pin Codex CLI `0.169.0`, `gpt-6.1-sol`, low reasoning and disabled memory
  retrieval. Abort before any model calls if the CLI or model is unavailable.
- Primary outcome: workflow-complete and oracle-verified; report paired
  `multi_borrow - single` and `multi_borrow - multi_fixed` differences and
  deterministic task-cluster bootstrap intervals. Secondary outcomes: raw
  oracle correctness, workflow completion, calls reserved/observed, report
  rejections, model-turn and peer-reserve denials, actions, latency and tokens.
- Run exactly 18 arms once, in preregistered order. Stop on infrastructure
  failure and retain completed records; never substitute or rerun a task. If
  `multi_borrow - single` is negative, stop this line without a larger study.
  A positive six-cluster result only warrants a separately preregistered
  larger study; it cannot close Issue #6.
- Retain answer-free records only: task IDs, encoding names, states, booleans,
  counts, timings and aggregate usage. No components, answers, candidate values
  or paths, oracle contents, or raw model messages enter tracked files.
