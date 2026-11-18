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
