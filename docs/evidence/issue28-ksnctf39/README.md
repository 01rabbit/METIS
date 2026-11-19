# Issue #28: inspectable evidence export

This directory is a **redacted export** of METIS run
`0045b063168045c289eaef276dab21c2`, prepared for PR #47 review. It is
not the original run database.

Run from the repository root:

```sh
PYTHONPATH=src .venv/bin/python scripts/verify_issue28_evidence.py \
  --database docs/evidence/issue28-ksnctf39/evidence.sqlite --public-bundle
```

The export contains all 3,739 original event rows, including their original
payloads, timestamps, previous hashes and digests, so the event chain and its
terminal `official_ksnctf` event can be checked independently. It also contains
the two verdict labels and timestamps, a restricted adapter/challenge binding,
the public encrypted ZIP, and only the counters and identity fields required
from the private checkpoint. The official ZIP SHA-256 is
`ff663a29abc5f0ded2c3456bc731b1b21329eb95914286733c40364624e5d8f5`.
The verifier checks the ordered 24 probe windows and all 88 × 8 full-scan
windows from the chained event payloads, including each `next_index`, scanned
width and completion marker. The private checkpoint alone is not the proof of
full coverage.

The export omits authentication state, candidate HMAC digests, the recovered
key, share contents, the answer, private shard references, and unrelated runs.
The checkpoint in this public bundle is deliberately redacted, so the verifier
uses `--public-bundle` to accept its public file mode. The same verifier without
that option checks the mode-0600 checkpoint in the original local run state.

The event hash chain detects corruption of these exported rows. It is not a
signature by ksnctf, and the verdict rows are METIS's recorded response to the
official adapter, not a server-signed receipt. The original local run state
remains available for comparison by an authorized reviewer with local access.
