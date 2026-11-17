# Issue #5 adaptive replanning micro-evaluation

## Scope

This offline demonstration covers one deliberately blocked strategy: Base64
decoding an input that is actually hex encoded. `FixtureProvider` observes the
controlled invalid-input result and selects the distinct `hex_decode` action.
The runtime classifies parser rejection as `failure_kind=invalid_input` without
writing decoded payloads to the event log. The run trace records that failed
tool observation, then logs the rationale
`Base64 decoder rejected input; test hex representation.` alongside the
selected alternate action before its runtime execution. Other failures such as
container/runtime errors halt the fixture provider instead of implying a
different encoding. Valid Base64 that produces non-UTF-8 bytes is separately
classified as `invalid_text` in the worker and cannot trigger the hex
hypothesis. A container regression for `/w==` covers that classification but
was skipped in this host run because Docker/cgroup-backed tests are unavailable.
A separate pinned baseline always selects Base64 first and
never changes strategy after its first action. Exact duplicate actions are
blocked by the runner.

## Paired comparison

The test uses 30 deterministic private-oracle fixtures (15 Base64, 15 hex),
generation seed `20261117`. Both policies receive the same initial Base64
action, local tool runtime, three-action cap, ten-second wall clock and
two-second per-tool timeout. Candidates count as solves only when the separate
mode-0600 fixture oracle verifies them. The paired bootstrap uses seed
`20261118`, 10,000 resamples, and percentile bounds.

| Policy | Verified solves | Mean tool actions |
| --- | ---: | ---: |
| Evidence-conditioned fallback | 30/30 | 1.5 |
| Pinned first-action baseline | 15/30 | 1.0 |

The paired solve-rate difference is 0.5, with a 95% paired bootstrap interval
of [0.333, 0.667]. The extra adaptive action on hex fixtures is the intended
cost of recovering from the invalid Base64 parse. This is deterministic,
synthetic mechanism evidence; it does not estimate real-model performance or
general CTF solve rates.

## Reproduction

```text
.venv/bin/python -m pytest -q tests/test_runner.py
...............ss                                                        [100%]
.venv/bin/python -m pytest -q tests/test_runner.py tests/test_runtime.py
.......................sssssssss                                         [100%]
```

The nine skipped tests require the optional real Docker integration image and
available cgroup v2 enforcement; this means the worker's `/w==` regression is
present but not observed on this host. Ruff and mypy also passed on the changed
source and full source tree. Broader P4 gates remain open: generalized
hypothesis confidence scores, contradiction and stuckness handling,
semantic-equivalence repeat detection, diverse held-out dead ends, and
real-model controlled comparisons.
