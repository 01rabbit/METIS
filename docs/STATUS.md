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

- Remote services (`metis remote`): suggestion-only statement parsing, explicit
  per-run TCP/TLS grants, bounded scripted exchanges and solver pipes,
  DNS-rebinding refusal, transcripts saved as scoped artifacts.
- Dynamic sandbox (`metis sandbox`): immutable image, no network, read-only
  root, no host mounts, capability-free unprivileged user, resource limits;
  run/strace/ltrace/gdb/script modes; bundled Dockerfile with pwntools.
- Platforms: rCTF adapter (team-token login, catalog, open, strict `kind`
  verdicts, `timeLeft` cooldown) and optional scoped JavaScript rendering.
- Claude Code: project skill, `/ctf` command, eight category subagents mapped
  to `metis plan` roles, startup prompt via `./start --agent claude`.

## Observed evidence

The local rehearsal exercised the full generic path: URL statement/file
acquisition, decoding, an intentional incorrect official submission, a recorded
revised hypothesis, a corrected verified submission, abstract success/failure
knowledge storage, retrieval on a second challenge, and a first-attempt verified
submission there. Random rehearsal answers were not stored in source or reusable
knowledge. This is integration evidence, not a general solve-rate measurement.

Final test, lint, type, build, bootstrap, and fresh-clone results for this
increment are recorded in `docs/reports/codex-native.md` after validation.

The 2026-11-12 completion increment is recorded in
`docs/reports/completion-2026-11-12.md`, including a real Docker run of the
sandbox (gdb, strace, script mode, network and filesystem isolation probes) and
a real Chromium rendering check.

## Boundaries and remaining work

Untrusted challenge programs are not executed on the host; dynamic analysis
needs a local container engine and the sandbox image. The bundled Dockerfile
build itself was not run in validation because registries were unreachable
there. Platforms other than CTFd, rCTF and ksnctf, and site-specific verdict
formats, need the generic form verifier or a new adapter.

The broader P0-P8 master plan remains a research roadmap. This increment does
not claim universal CTF solving, live competition success, macOS validation,
browser automation, or safe hostile-code execution. The optional standalone
model/container experiments remain separate from the default Codex workflow.
