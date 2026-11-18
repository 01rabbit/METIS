# Issue #6 real-model follow-up pilot preregistration (2026-11-17)

## Question

Under matched run-level budgets, does concurrent specialist decomposition reduce
elapsed time on small independent decoding tasks compared with one specialist
handling the same two components? This is a synthetic local-fixture pilot, not
an AlpacaHack solve-rate benchmark.

## Frozen design

- **Model:** `gpt-6.1-sol`; Codex CLI `0.169.0`; reasoning effort `low`.
- **Arms:** one crypto specialist receives both registered artifacts; the
  concurrent arm assigns one artifact to each of two specialists. Both arms
  receive the same inputs, task description, oracle, and final SHA-256 rule.
- **Tasks:** six seeded cases (three encoding-pair families, each repeated with
  fresh bytes): Base64+hex, Base32+Base64, hex+Base32. Each component is 12
  random bytes. The final answer is SHA-256 of component 0, a NUL byte, and
  component 1. The oracle is mode 0600 and outside each run's artifact root.
- **Budgets per run:** eight reserved model calls, four mediated artifact
  actions, two concurrent slots, 600 seconds. MUNIN retrieval is disabled.
  Candidate and report actions do not increase the artifact-action cap.
- **Randomization:** use a fixed seed to randomize single/multi arm order for
  each pair before any model call. All cases and the order are generated before
  execution.
- **Scoring:** only the protected local oracle verdict counts as verified.
  Failed, incomplete, invalid, or timed-out runs score zero. Do not retry a
  task after a substantive model failure; the CLI's bounded transient retry is
  included in consumed calls.
- **Metrics:** paired oracle verdict, elapsed seconds, reserved/provider calls,
  input/cached/output/reasoning tokens when reported, mediated actions, report
  completion, and cost (record `unknown` if unavailable). Keep answer values,
  oracle contents, and candidate paths out of GitHub/run logs.
- **Exploratory decision rule:** report the six-pair result descriptively. Do
  not close Issue #6 or claim a general gain from this pilot. Continue to a
  repeated, diverse benchmark only if the observed latency/cost tradeoff
  justifies the additional calls. The acceptance gate still requires a
  pre-registered comparison over at least 30 distinct tasks with two
  repetitions and paired uncertainty, plus a demonstrated gain.

## Limits

This small pilot is designed to validate the controlled real-model measurement
path and detect a potentially useful latency signal. Its task family is narrow,
and it cannot satisfy the issue's diversity, repetition, uncertainty, or
generalization requirements by itself. Dollar cost may be unavailable from the
Codex CLI. The claim scope is Codex CLI only.
