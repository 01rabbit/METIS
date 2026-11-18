# Issue #8: AlpacaHack Daily `Not so Pyf**k` evaluation (2026-11-18)

## Result

The user-authorized, previously unsolved AlpacaHack Daily archive for `Not so
Pyf**k` (Misc / Medium, released 2026-08-09) was analyzed in a separate METIS
held-out run (`b92de413b0b44a7d9eca470cd57f0320`). The official archive was
downloaded from the challenge page. Its jail accepts ASCII input, limits the
number of distinct alphabetic characters to three, and then evaluates the
input.

A bounded probe generated an expression whose source uses only three distinct
letters and three-digit octal string escapes. The expression passed the local
jail's checks and executed inside METIS's `linux/arm64` Docker sandbox with
network disabled and no host mounts. The probe compared the resulting final
stdout content to the value bundled in the archive, but emitted only booleans
and counts. The final sandbox result was `ok: true`, `candidate_ascii: true`,
`candidate_distinct_letters: 3`, `jail_exit_code: 0`, and
`local_package_flag_match: true`; no answer value was recorded in this report,
the event ledger, or Git.

The initial hexadecimal-escape probe was rejected by the local alphabet check
because `a`–`f` in hex digits count as letters. A corrected octal-escape probe
passed. An initial comparison also failed because the jail prompt preceded
the program output; the probe was corrected to compare the final output
content while keeping both values hidden. These failures and corrections are
retained in the run ledger.

## Official verification follow-up

The browser was reauthenticated as `mr-rabbit`, and the challenge page exposed an
enabled submit form. The first candidate was the value bundled as `flag.txt`;
the official UI returned `Incorrect flag.` This directly disproved the earlier
assumption that archive-local equality was sufficient evidence of the target
answer.

The official `Spawn Challenge Server` control returned one instance endpoint.
After granting only that host and port in the same METIS run, a bounded
three-letter octal-escaped expression read the live instance's `/flag-*` file.
Its value differed from the archive value (compared by SHA-256 only). The live
candidate was submitted once in the official browser; the page changed the
challenge control to disabled `Solved`. `metis web attest` recorded the
browser-observed verdict as `correct`, and the write-up's protected answer
check returned `match`. No candidate value was placed in the run events, report,
or Git.

## Verification boundary

This is one official solve and a positive local sandbox datapoint, not a
repeated held-out benchmark. The archive-derived candidate was officially
rejected; the live instance candidate was officially accepted. Treating the
two as different values is based on their observed digest mismatch. This does
not establish whether all official instances randomize the flag.

This single task does not meet P7's repeated-run, confidence-interval,
solvability-control, comparable-budget, cost/latency, or ablation requirements.
It does not establish a general AlpacaHack solve rate or close Issue #8.

## Evidence and isolation

- METIS run: `b92de413b0b44a7d9eca470cd57f0320` (original evaluation split
  `unlisted`; final status `solved`; chain valid).
- Static jail source and archive listing: event sequences 37 and 41.
- Final successful sandbox invocation and result: event sequences 68–69.
- Official incorrect archive-value attestation and corrected live-instance
  solve attestation are in the same run; no raw candidate is in the ledger.
- Runtime: 0.023 seconds; `linux/arm64`, immutable image
  `sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b`,
  Docker network `none`, no host mounts.
- One official instance endpoint was granted and used; two official browser
  submissions were made (one incorrect archive value, one accepted live value).
- Write-up: `writeups/alpacahack-daily-2026-08-metis-evaluation/not-so-pyfk-not-so-pyf-k.md`.

Keep Issue #8 open.
