# METIS implementation status

## Codex-native solve workflow

The active implementation is on `metis-full-implementation`. Codex supplies the
reasoning, so this workflow has no model API key or Docker prerequisite.

Implemented:

- Authorized URL intake for generic HTML and CTFd, scoped redirects and
  downloads, bounded response sizes, DNS rebinding checks, proxy/TLS support,
  private cookies, and optional token/cookie authentication.
- Private local challenge sessions with action/time budgets, file snapshots,
  exact artifact scope, recovery, cancellation, and a run board.
- Thirty-seven bounded data/crypto helpers and twenty-six static artifact
  analyses spanning common crypto, web, forensics, reverse engineering, pwn
  preparation, and misc formats.
- Official CTFd answer verification and fail-closed generic HTML form
  verification. HTTP 200, reflected candidates, and local regex extraction are
  not accepted as proof.
- Duplicate rejection, submission caps, rate-limit handling, and a required
  post-feedback hypothesis revision before a new candidate after an incorrect
  verdict.
- MUNIN technique cards with evidence/run provenance, successful-solve gating,
  failure-evidence gating, held-out exclusion, secret/flag guards, search, and
  retrieval during later intake.
- A project-local setup script, six synthetic category exercises, and a local
  CTFd-shaped rehearsal server.

## Observed evidence

The local rehearsal exercised the full generic path: URL statement/file
acquisition, decoding, an intentional incorrect official submission, a recorded
revised hypothesis, a corrected verified submission, abstract success/failure
knowledge storage, retrieval on a second challenge, and a first-attempt verified
submission there. Random rehearsal answers were not stored in source or reusable
knowledge. This is integration evidence, not a general solve-rate measurement.

Final test, lint, type, build, bootstrap, and fresh-clone results for this
increment are recorded in `docs/reports/codex-native.md` after validation.

## Boundaries and remaining work

Untrusted challenge programs are not executed on the host. The current cloud
runtime cannot enforce the isolation needed for hostile dynamic binaries, so
dynamic pwn/reverse execution remains unavailable unless a separately enforced
sandbox is provided. JavaScript-only pages, non-CTFd platform APIs, unusual
download flows, or site-specific verdict formats may need a dedicated adapter.

The broader P0-P8 master plan remains a research roadmap. This increment does
not claim universal CTF solving, live competition success, macOS validation,
browser automation, or safe hostile-code execution. The optional standalone
model/container experiments remain separate from the default Codex workflow.
