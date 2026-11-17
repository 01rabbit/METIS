# Issue #8: AlpacaHack Daily `Not so Pyf**k` probe (2026-11-18)

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

## Verification boundary

This is a positive, single-task **local archive/jail execution** datapoint,
not an official platform solve. The METIS web run has no authenticated session,
no configured verifier, and no verdict; no server was started and no
submission was made. The local packaged value is not an independent official
oracle. The evidence must not be counted as an independently verified flag
for the Issue #8 benchmark gate.

The probe adds one held-out Misc task and a reproducible sandbox outcome, but
does not meet P7's repeated-run, confidence-interval, solvability-control,
comparable-budget, cost/latency, or ablation requirements. It does not establish
a general AlpacaHack solve rate or close Issue #8. The run remains
`planning`/unverified.

## Evidence and isolation

- METIS run: `b92de413b0b44a7d9eca470cd57f0320` (evaluation split `unlisted`).
- Static jail source and archive listing: event sequences 37 and 41.
- Final successful sandbox invocation and result: event sequences 68–69.
- Runtime: 0.023 seconds; `linux/arm64`, immutable image
  `sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b`,
  Docker network `none`, no host mounts.
- Official endpoint grants: none. Official submission: none. Official verdict:
  none.

Keep Issue #8 open.
