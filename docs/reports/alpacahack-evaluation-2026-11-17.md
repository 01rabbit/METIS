# AlpacaHack Daily evaluation — 2026-11-17

## Scope and result

The user-authorized evaluation board was AlpacaHack Daily for August 2026. Before
working each selected challenge, its page showed an enabled submission form and
the account dashboard showed it as unsolved. Official submissions were made
only through the authenticated browser form. No challenge write-up was
consulted, no answer was stored in this report, and each solved challenge has a
separate write-up without the answer value.

| Challenge | Category | METIS run | Official evidence |
| --- | --- | --- | --- |
| Let's analyze system calls | Rev | `1709125dc8f645f4a7c72a86efa1d210` | `metis web attest`: `official_browser_observed` |
| Springing | Web | `ea91c4d7c2c748bc9277f5e39f1cb80a` | `metis web attest`: `official_browser_observed` |
| Happy Birthday | Crypto | `1f8c26a2f7bd437e878297d37955fb0b` | Browser displayed `SOLVED!`; `metis web attest`: `official_browser_observed` |
| Password, Please | Misc | `4e139020ad554e2a9d061df07c621853` | Browser card changed to solved, form disabled, dashboard 4/14 and Misc 1/6; `metis web attest`: `official_browser_observed` |

After the fourth solve, the authenticated dashboard showed 4/14 for August,
including Rev 1/2, Web 1/4, Crypto 1/2, and Misc 1/6. The METIS evaluation board
showed 4/4 challenges solved. This exceeds the plan's minimum live-evaluation
gate of three official solves across three non-Welcome categories, including
both designated final-evaluation challenges.

## Happy Birthday evidence

The registered challenge archive's Python source compares the first five bytes
of SHA-256 digests and requires different inputs with `user=` and `admin=`
prefixes. A bounded, local birthday search found a pair satisfying those
conditions. METIS connected only to the exact endpoint displayed for the one
instance spawned from the challenge page (`34.170.146.252:32411`). The service
accepted the pair and returned its response. The response was submitted once
through the browser form; the page then displayed `SOLVED!`, the solve counter
increased, and the form became disabled as solved. The instance was no longer
listed online afterward.

The assigned Crypto specialist reported the 40-bit collision strategy and
source evidence; an independent critic checked the hypothesis. Daybreak
performed the collision search and official submission. Therefore this result
is live integration and browser-verification evidence, **not** proof that an
autonomous METIS model completed the challenge. It does not satisfy the P1
acceptance gate for autonomous model solving or the comparative benchmark
gates.

## Current limits

- Password, Please was a development candidate, not a designated final-evaluation challenge. Daybreak used the observed Bash glob comparison to direct one bounded connection to the single challenge instance, then submitted once in the browser. This is official integration evidence, not an autonomous specialist solve; it does not count toward P1 model autonomy.
- No issues were closed based on this evaluation.
- PR #31 remains Draft. Its three required CI jobs passed on head `8f85ce5`;
  checks must be inspected again after this report and write-up update is pushed.
- The issue gates for bounded ZipCrypto/Stay recovery, Linux real-Codex and
  sub-agent isolation, post-reauthentication KSNCTF #33, and P1–P8 research,
  benchmark, and operational acceptance remain separate work.
