# METIS

METIS is a Codex-native workflow for authorized CTF challenges. Given a problem
URL or local distributions, it acquires bounded inputs, helps Codex inspect and
solve them, submits an exact candidate to the official verifier, revises failed
hypotheses, and saves abstract techniques for later challenges.

Codex supplies the reasoning. The normal workflow needs neither a separate model
API key nor Docker.

## Start

```sh
./metis-codex
```

This launcher installs missing project-local dependencies, starts Codex in the
repository, checks readiness, and asks for the problem URL or distribution files
plus any platform details that are actually needed. It enables the Codex
`cli_daybreak` and `multi_agent` features and instructs Daybreak to coordinate
the solve while focused lower-tier agents handle independent work in parallel.
The instructions cap unnecessary fan-out and context duplication to conserve
tokens. The launcher also uses Codex automatic approval review so ordinary
workspace operations do not repeatedly stop for confirmation.

After intake, `metis codex plan RUN_ID` creates a bounded specialist wave using
patterns adapted from public CTF and cyber-agent research. The reviewed sources,
licenses, and adopted boundaries are documented in the
[open-source design review](docs/OPEN_SOURCE_DESIGN_REVIEW.md).

For manual preparation, run `python3 scripts/setup.py` followed by
`.venv/bin/metis doctor`.

A standard CTFd problem can also be opened directly:

```sh
.venv/bin/metis web open https://ctf.example/challenges --adapter ctfd --challenge-id 12
```

METIS downloads recognized same-origin distributions into a private snapshot,
returns triage and prior MUNIN knowledge, and exposes bounded static analysis and
data tools. Submit candidates on stdin with `metis web submit RUN_ID`. The result
is a verified solve only when the official adapter confirms it.

See [CTF quick start](docs/CTF_QUICKSTART.md) for the practical flow and
[METIS skill](.agents/skills/metis/SKILL.md) for Codex instructions.

## Current capabilities

- Generic HTML and CTFd acquisition, scoped redirects/downloads, optional local
  token or cookie authentication, and private cookie persistence.
- Encodings, hashes, classical ciphers, XOR, integer/RSA helpers, AES with known
  keys, packing, cyclic patterns, and candidate extraction.
- Bounded static inspection for archives, images, audio, packet captures,
  SQLite, PDF text, Java classes, PE, ELF, and several CPU disassemblies.
- Official CTFd verdicts and explicitly configured HTML-form verdicts; reflected
  candidates and HTTP status alone are rejected as proof.
- Duplicate-answer prevention, rate-limit handling, post-failure hypothesis
  revision, resumable state, and evidence-backed reusable technique cards.
- Six synthetic offline category exercises and a local CTFd-shaped rehearsal
  server for repeatable tests.

Uploaded programs are never executed on the host. This environment cannot
safely run hostile binaries, so dynamic exploitation requires a separately
enforced sandbox. JavaScript-rendered pages and unusual competition APIs may
need an adapter or a manually supplied distribution. These limits do not block
the static and network submission workflow above.

## Development

Run `python3 scripts/setup.py --dev`, then `pytest`, `ruff check src tests scripts`,
and `mypy src/metis`. The optional standalone provider/container experiments are
kept for research but are not part of the default solve path. The broader
[master implementation plan](docs/MASTER_IMPLEMENTATION.md) remains a research
roadmap rather than a claim of completion.

Use METIS only for competitions, local fixtures, and infrastructure that the
user is authorized to test. Keep credentials and private flags out of Git and
reusable memory.
