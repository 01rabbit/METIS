# AlpacaHack Daily Renda probe (2026-11-18)

## Scope and selection

The authenticated AlpacaHack Daily page showed today's challenge as solved. In
the July 2026 archive, account progress showed 1/31 Daily solves, Web 1/11, and
Rev 0/3. The selected challenge, [Renda](https://alpacahack.com/daily/challenges/renda?month=2026-07),
is Rev, released July 4, 2026, and was therefore an unsolved account challenge
at intake time. This is one user-unsolved archived challenge, not a held-out
benchmark set.

## METIS intake

- Run: `a6d441d184ec4a7e9c1d7e20c4955af7`
- Evaluation split: `unlisted`
- Budget: 60 actions, 1,200 seconds; no network endpoints granted
- Official artifact: `index.html`, 20,907 bytes, SHA-256
  `32c8342cdfbb5f89f93129532f8a5c236b936bdf6ab6e08ce6334c1a3f64ce1e`
- METIS `overview` classified it as UTF-8 text. The page says to click 100,000
  times to get the flag; its inline JavaScript is heavily obfuscated.

## Result and limits

The artifact is registered in METIS and remains at planning. No challenge
JavaScript was run on the host, no official submission was made, and no
official verdict or verified flag exists. This exploratory probe does not meet
Issue #8's repeated held-out benchmark, protected-oracle, solvability-control,
cost/latency, or ablation requirements. Keep Issue #8 open.

## Isolated static follow-up

The METIS sandbox used the immutable Linux ARM64 image with no network or host
mounts. A sandbox-only check confirmed that the image has no Node.js, QuickJS,
Deno, Bun, or browser runtime. A restricted arithmetic-only parser evaluated
the numeric expressions in the obfuscated output arrays and emitted metadata
only: 53 printable characters were derived, but the result did not match the
page's `Alpaca{...}` format. The candidate text was neither emitted nor saved.
This is not a solve; the surrounding obfuscated control flow still needs
analysis to establish whether those arrays are the active output path.
