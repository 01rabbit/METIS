# Issue #8 AlpacaHack Rev memory comparison preregistration

This answer-free record precedes every held-out model call. The earlier
`gpt-6.1-sol` protocol hash in commit `3b229f9` is superseded because its
Codex CLI ping failed. The new model passed the isolated ping; no held-out
model call occurred under the superseded hash. The validated
protocol is `issue8-rev-memory-protocol.json`, SHA-256
`2204980da039f6716451a59817069ffeb743977e293e40811a8cd455426bc5bb`.
`python -m metis.evaluation.heldout_protocol prepare` prints its fixed eight-slot
schedule. Any task, arm, prompt, model or budget change requires a new protocol
hash and a new record before model execution.

- Tasks: official AlpacaHack Daily `misdirection` and `read-a-binary`, both Rev.
  Distribution SHA-256 values are in the protocol. The authenticated `mr-rabbit`
  account showed enabled submission controls for both on 2026-11-19.
  Each run receives the official ELF and the same answer-free task brief for
  its arm. The brief SHA-256 values are `30f9f9116aa59fb56941ee30f5ea2ef64b1f81539c3c72d7903e01d632b96dad`
  for `misdirection` and `bb45d30b87922b15080f5c75cc8a7b2cf951319356af0da3fe5cbc169cbe229e`
  for `read-a-binary`. They reproduce the official statement and source URL.
  Two scoped artifacts make the standard METIS plan delegated (artifact triage,
  Rev specialist, independent critic) in both arms; no artificial category is
  added.
- Independent controls: each official ELF was solved separately without public
  writeups, and its candidate was accepted by the challenge binary in a METIS
  no-network/no-host-mount sandbox. Exact candidates and commitments are in
  private files outside Git and outside specialist access. No official server
  submission has occurred. The control establishes local feasibility, not an
  official verdict. Isolated audit DBs are
  `/private/tmp/metis-issue8-oracle-read/state.sqlite` (run
  `8982997b8e8442e0acd438b6fa57104a`, final sandbox observation 17) and
  `/private/tmp/metis-issue8-oracle-misdirection/state.sqlite` (run
  `970cdebe1f514cd498737ef3a8e68892`, sandbox observation 5). The control
  process checked that candidate bytes were absent from their DB/WAL files.
- Exposure: `unknown` for both older public tasks. The model may have seen them
  before this study; the acceptance solve metric must exclude them. The paired
  results are exploratory and cannot close Issue #8.
- Design: two tasks, two repetitions, `full` and `without_memory`, balanced
  deterministic order. Both arms use the same prompt, model, planner, specialist
  limit and per-run budgets. The only planned difference is the frozen MUNIN
  card: the `full` arm receives prior practice card SHA-256
  `835c160eaeea4845143a21958b78a6f74057fd6d0ac3b643cb8f8a05d474633e`;
  `without_memory` receives none.
- Model/runtime: `gpt-6.2-sol` through Codex CLI `0.169.0`, METIS code
  `1dab7405bec87b84d85374c21ff838a10b21c176`, scheduler host `bridge`.
  The pinned sandbox image is
  `sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b`
  on `linux/arm64` with QEMU for the official x86-64 ELF files. A changed
  runner or sandbox requires stopping and registering a new study.
- Budget: at most six model calls, eight mediated actions and 600 seconds per
  run; aggregate declared caps are 48 calls and 4,800 seconds. Tokens are
  bounded at 50,000 per run in analysis, but provider enforcement and dollar
  cost may be unknown and must be reported as such. Do not extend exhausted
  runs to evade these caps.

Each run will be created and bound in schedule order, with the exact task
artifact, common prompt and practice-card snapshot fixed before its first
work event. Specialist sessions have no inherited history, no public web
search and no direct oracle access. A candidate matches the protected local
oracle only if its exact bytes match the private commitment. Local success
is recorded separately from any later official platform verdict. Do not
publish candidates, raw flags, credentials, private oracle files or the run DB.
