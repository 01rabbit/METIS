# Issue #6 conditional delegation pilot: frozen design

This is a new hypothesis after the registered negative-primary stop for dynamic
borrowing. It does not extend or rerun that study and cannot alone close P5.

- Study `issue6-conditional-pilot-2026-11-18`; task seed `2026111828`, arm-order
  seed `2026111828 XOR 0x6A09E667`. Twelve new clusters `cond12-00` through
  `cond12-11`: two each of Base64/Base32, Base64/hex, Base64/Base85,
  Base32/hex, Base32/percent, and hex/Base85. Each cluster has two independent
  printable 12-byte components and one trial per arm.
  Runs use the `practice` split; they are not held-out acceptance trials.
- Arms are `single` (one crypto specialist, up to eight calls) and
  `conditional` (crypto lead up to four calls; if it lacks both a private
  candidate and a completed report, a forensics specialist receives both
  artifacts with up to four remaining calls). The controller computes the
  identical SHA-256 composition and protected-oracle check for both arms.
- Both arms share caps of eight reserved model calls, four mediated actions,
  two slots, and 600 seconds. Pin Codex CLI `0.169.0`, model `gpt-6.1-sol`,
  low reasoning, no memory retrieval. Abort before calls if the CLI pin fails.
  Arm order is seeded and randomized per cluster. No reruns or substitutions.
- Primary outcome is a completed candidate-producing assignment with an
  oracle-verified final digest. Report the paired conditional-minus-single
  difference and a deterministic task-cluster bootstrap interval. Also report
  fallback dispatches, calls, actions, time, terminal states, and rejections.
  A nonpositive primary result stops this policy. A positive 12-cluster pilot
  only motivates a separate preregistered held-out replication.
- Save answer-free records only; components, candidates, digests, raw model
  messages, oracle values, and private paths stay outside Git. Interrupted
  runs leave `.partial.json`, which is never accepted as the final 24-arm
  dataset. A finalized dataset requires each distinct case-arm exactly once.
