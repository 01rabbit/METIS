# Issue #8: AlpacaHack Daily `RFC100008` official solve (2026-11-18)

## Result

The user-authorized AlpacaHack Daily `RFC100008` challenge was solved through
its official browser verifier. The logged-in challenge page changed to disabled
`Solved`, and the visible solve count increased from 168 to 169 after one
prepared submission. METIS recorded `official_browser_observed` with
`verified: true`; the per-problem write-up answer check returned `match`.

## Method

The registered archive contains a small Flask application. Its source generates
an uppercase 16-hex-character method with `secrets.token_hex(8).upper()`,
registers only that method on `/rfc100008`, and returns the flag in the handler.
The application runs in the challenge container on port 3000.

The official `Spawn Challenge Server` UI returned one instance endpoint. After
granting only that endpoint to the METIS run, an `OPTIONS /rfc100008` request
returned HTTP 200 with an empty body and an `Allow` header containing `OPTIONS`
and the instance's generated method. One request using that exact method and
route returned the expected response shape. The candidate stayed in a mode-0600
temporary file and was submitted once through the logged-in official browser.
The actual method token and flag are omitted from this report and the run log.

## Evidence and limits

- METIS run: `01f1bc168d3d49288334506fa808da59`; audit chain valid, final status
  `solved`.
- The official HTTP request was restricted to `34.170.146.252:22187` and the
  single route `/rfc100008`; no scan or other endpoint was used.
- The answer is stored only in the protected METIS answer vault. The write-up
  contains an answer reference and a successful official-answer check.
- The run was classified `unlisted` when opened because no existing write-up
  mapped this problem. It was not preregistered as held-out and did not use a
  repeated-run protocol or matched controls. Do not count it as P7 held-out
  benchmark evidence.

Issue #8 remains open. Repeated held-out runs, confidence intervals,
solvability controls, comparable budgets, cost/latency reports, and ablations
remain unmet.
