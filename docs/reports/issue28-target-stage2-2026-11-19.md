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
5,204 seconds. This is below the preregistered 5,400-second scan gate and 704
full-domain actions, below the 900-action task ceiling. It is a feasibility
estimate, not a target completion or a bound on unobserved hit-heavy regions.

The task-specific runner stores only private shard references, aggregate
timings/counts, run identity and resumable cursors in a mode-0600 checkpoint.
It fails closed on an in-flight action after interruption, stalled cursors,
isolation errors, unsafe shard paths and exhausted budgets. The exploration
limit is two hours total, with at most 90 minutes for Stage 2 scanning. Keys,
shares and candidates are neither printed nor written to Git. Full scan,
recovery, all-member CRC check and official verdict are pending.
