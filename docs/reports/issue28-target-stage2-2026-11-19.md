# Issue #28: official #39 Stage 2 feasibility and bounded continuation

The authorized ksnctf #39 run `0045b063168045c289eaef276dab21c2` retains
the official 2,353-byte archive (SHA-256
`ff663a29abc5f0ded2c3456bc731b1b21329eb95914286733c40364624e5d8f5`)
and seven mode-0600 Stage 1 shards. The audit chain was valid, with 65 charged
actions, no active operations, and no verified solve before this follow-up.
The run had expired; a 1,800-second operator-authorized extension resumed it.
The fixed networkless ZipCrypto sandbox image was present on Linux arm64.

The private Stage 1 records contain 360 hits. Exactly 88 have a nonempty
shared key1 product interval, with summed interval width 98,222,960. A
deterministic sample selected eight eligible hits across interval-width ranks.
For each, the Stage 2 tool scanned three disjoint 2^20-guess windows (start,
middle, end), 24 bounded actions and 25,165,824 raw guesses total. All windows
completed; none yielded a Stage 2 hit. The slowest observed worker seconds per
guess, multiplied by the full 88 × 2^26 domain and a factor of two, projects
5,204 seconds. This was below the preregistered 5,400-second scan gate and 704
full-domain actions, below the 900-action task ceiling. It was a feasibility
estimate, not a bound on unobserved hit-heavy regions.

The task-specific runner stores only private shard references, aggregate
timings/counts, run identity and resumable cursors in a mode-0600 checkpoint.
It fails closed on an in-flight action after interruption, stalled cursors,
isolation errors, unsafe shard paths and exhausted budgets. The exploration
limit is two hours total, with at most 90 minutes for Stage 2 scanning. Keys,
shares and candidates were neither printed nor written to Git.

The continuation completed all 88 eligible hits in 704 Stage 2 scan actions.
Four Stage 2 hits were found; bounded product recovery found one full key.
The complete task used 866 charged actions: 24 probe, 704 scan and 138 recovery.
The key was stored only in a mode-0600 run-private shard. A separate check
decrypted all seven members with the recovered state, verified their predicted
random headers and CRCs, and XORed seven equal-length, 159-byte shares.
The result contains one marker-led printable token surrounded by padding.

The first official submission incorrectly included five leading spaces from
the printable padding and received `incorrect`. An evidence-based hypothesis
revision was recorded in the run. Submitting the marker-led token without the
padding received the official ksnctf `correct` verdict; METIS run status is
`solved`. This establishes the official #39 solve for Issue #28. The report
intentionally omits the key, shares, and answer. The private checkpoint and
official verdict remain in the run state.

The first review of this runner identified three checkpoint integrity defects:
uncertain operations could clear the in-flight marker, a fixed temporary name
could block restart, and a reported key shard was not validated before success.
The follow-up change keeps the marker until validated progress is committed,
uses unique same-directory private temporary files, and validates the key
shard's run path, file type, mode and key structure. Negative-path and restart
tests cover rejected, malformed, stalled, failed and symlink cases. These
changes harden future execution; the earlier official verdict is independently
recorded in the original run state.

## Read-only evidence cross-check

Run from the repository worktree with access to the original local run state:

```sh
PYTHONPATH=src .venv/bin/python scripts/verify_issue28_evidence.py \
  --database /Users/mao/Developer/GitHub/METIS/.metis-state/metis.sqlite
```

Observed on 2026-11-19 (JST):

| Field | Value |
| --- | --- |
| Run ID | `0045b063168045c289eaef276dab21c2` |
| Registered ZIP SHA-256 | `ff663a29abc5f0ded2c3456bc731b1b21329eb95914286733c40364624e5d8f5` |
| Audit chain / terminal sequence | valid / `3738` |
| Terminal digest | `4ef4edf71c42b7c097bda78a1ca28fb28229bed211efb7ddf6f766046c4d481c` |
| Audited Stage 2 / recovery actions | `728` (`24` probe + `704` full) / `138` |
| Private full-scan checkpoint | `88/88` eligible hits, `866` task actions, no in-flight action |
| Official adapter / challenge | `ksnctf` / `39` |
| Submission verdicts | `incorrect`, then `correct` (one attempt each) |
| Correct verdict / solved event | `2026-11-18T23:48:10.021560+00:00` / `2026-11-18T23:48:10.058090+00:00` |
| Solved event verification | `official_ksnctf` |
| Active operations | `0` |

The verifier opens the SQLite database read-only. It checks the archive bytes,
registered run and official adapter binding, private full-scan cursor, audited
tool counts, verdict sequence, and terminal event within 30 seconds of the
`correct` verdict. It outputs no answer, key, share or HMAC candidate digest.
The PR contains this verifier and the observed nonsecret result; the underlying
local database and private checkpoint are not committed. This is a cross-check
of METIS's recorded official response, not a cryptographically signed receipt
from ksnctf.

For reviewers without access to that local database, a restricted export is
included at `docs/evidence/issue28-ksnctf39/`. It contains the original event
chain and nonsecret verdict metadata plus a redacted checkpoint and the public
encrypted archive. Run the same verifier with `--public-bundle` as described in
the export README. The verifier checks the complete ordered Stage 2 window
sequence from hash-chained event payloads, so its coverage conclusion does not
depend only on the redacted checkpoint. The export does not turn the official
response into a server-signed receipt; it makes the locally recorded evidence
inspectable.
