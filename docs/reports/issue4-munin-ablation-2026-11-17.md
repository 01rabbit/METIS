# Issue #4 MUNIN retrieval ablation (2026-11-17)

## Scope

This is a deterministic policy-level experiment. It tests whether an abstract
MUNIN card changes the action ranking supplied to the same solver policy. It
does not measure LLM behavior or general solve-rate improvement.

The source run is an oracle-verified synthetic ROT13 exercise. Its card says to
test ROT13 on alphabetic ciphertext. The three target strings are different
from the source text and from each other. Both arms use the same `_rank_tools`
policy and the same candidate set `[base64_decode, rot13]`; retrieval-on lets
the retrieved card reorder that list, while retrieval-off receives an empty
brief and retains the baseline order. Each output is checked through the local
commitment oracle before the trial counts as solved.

## Observed result

Command:

```text
.venv/bin/python -m pytest -v tests/test_munin_integration.py
```

Output: `3 passed in 0.24s`.

For each of the three target fixtures, retrieval-on tried one tool and
retrieval-off tried two. All six submissions were oracle-verified. The paired
mean action difference was one action per target in this small deterministic
fixture set. Held-out and unlisted targets received no prior cards; existing
source-split mismatch and answer/credential redaction tests also passed.

## Limits

This demonstrates card transfer and its effect on one explicit candidate
ranking policy under a controlled ablation. The policy itself recognizes tool
names in card text, so this is not evidence that an LLM learned a reusable
technique or that MUNIN improves performance on unseen real challenges. The
three fixtures are too few for general statistical claims. Keep those claims
out of release and benchmark summaries.
