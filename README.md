# METIS

METIS is a Codex-native workflow for authorized CTF challenges. Given a problem
URL or local distributions, it acquires bounded inputs, helps Codex inspect and
solve them, submits an exact candidate to the official verifier, revises failed
hypotheses, and saves abstract techniques for later challenges.

Codex supplies the reasoning. The normal workflow needs neither a separate model
API key nor Docker.

## Start

```sh
./start
```

This launcher installs missing project-local dependencies and starts an installed
AI coding CLI in the repository. With Codex it enables `cli_daybreak` and
`multi_agent` when the installed Codex lists them (`codex features list`), and
automatic approval review when supported. Other agents use the same local
METIS commands, verifier, state, and knowledge store. The instructions cap
unnecessary fan-out and context duplication to conserve tokens.

For contests (Claude Code + tmux), use the contest launcher instead:

```sh
./play                 # menu: continue a contest or register a new one from its URL
./play CONTEST_ID      # continue directly; ./play --new URL registers and starts
```

It opens a tmux session with an interactive Claude Code window (started with the
contest's rules and a "fetch new challenges, report, clear handoffs" brief), a live
dashboard, and optionally swarm workers. Choosing a running contest re-attaches.
See [Tournament mode](docs/TOURNAMENT_MODE.md).

`./start` detects Codex, Claude, Gemini, OpenCode, or Aider. Select explicitly
with `./start --agent NAME`; see the
[compatibility guide](docs/AGENT_COMPATIBILITY.md) for validated boundaries.

After intake, `metis plan RUN_ID` creates a bounded specialist wave with distinct
roles, minimal context, turn limits, and centralized official verification.
`metis agent report` persists compact evidence without candidates, and
`metis agent synthesize` blocks unknown evidence, duplicate actions, secrets,
and incomplete waves. Reports survive restarts and work with any agent CLI.

For large events, `metis web catalog`, `metis contest add`, and
`metis contest dispatch` maintain a persistent tournament queue. The scheduler
balances expected points per minute with category coverage and dependencies.
Attack-defense mode prioritizes service recovery and patch regression checks.
See [tournament mode](docs/TOURNAMENT_MODE.md).

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

Official ksnctf problem URLs are recognized automatically (or use `--adapter ksnctf`):

```sh
.venv/bin/metis web open https://ksnctf.sweetduet.info/problem/2
```

The problem ID comes from the URL. `metis web submit RUN_ID` sends the stdin
candidate to the same-origin JSON API and accepts only its boolean `result: true`.
Successful submissions update the run to `solved` and permit success technique cards.

rCTF events use `metis web auth URL --kind rctf-team-token` once, then
`metis web catalog URL --adapter rctf` and
`metis web open URL --adapter rctf --challenge-id ID`. JavaScript-built pages can
be opened with `--render` (optional scoped headless Chromium:
`python3 scripts/setup.py --browser`).

Stored local platform credentials can be reviewed and retired by age. Preview
first, then add `--apply` to delete eligible credentials and their matching
authentication-origin cookies:

```sh
metis web credential-retention --older-than-days 90
metis web credential-retention --older-than-days 90 --apply
```

Credentials whose age is unknown are retained. This local operation does not
revoke credentials at the CTF provider or erase prior SQLite WAL, snapshots, or
backups.

Services announced as `nc host port` are reached with `metis remote`: `suggest`
lists candidates from the statement, `grant` records the endpoint the user
authorized, `exchange` runs a bounded JSON send/receive script, `pipe`
bridges an agent-written solver's stdin/stdout to the socket, `ssh` runs
commands and fetches files over SSH, and `connect` is an `nc`-like bridge.
Web challenge servers are reached with `metis web grant` and `metis web
request` (single or batched, shared cookie jar, any non-hop-by-hop header).
All of these honor the platform proxy, so they work inside agent sandboxes
such as Claude Code's where raw sockets and local DNS are blocked.

Challenge programs run only in `metis sandbox`: a fresh no-network, read-only,
capability-free container per call (Docker Desktop, OrbStack, Colima or Podman),
with `run`, `strace`, `ltrace`, `gdb` and `script` modes and pwntools inside.
Build the bundled image once with `metis sandbox build`.

Each CTF gets a directory under `writeups/` with one Markdown write-up per
problem (`metis writeup save`), a progress table, and a cross-CTF technique
index (`writeups/KNOWLEDGE.md`) generated from the MUNIN technique cards that
later challenges retrieve automatically.

To move or copy the checkout (another folder or another Mac), copy the whole
folder including hidden directories and run `python3 scripts/setup.py --all`;
see [migration](docs/MIGRATION.md).

See [CTF quick start](docs/CTF_QUICKSTART.md) for the practical flow and
[METIS skill](.agents/skills/metis/SKILL.md) for Codex instructions.

## Current capabilities

- Generic HTML and CTFd acquisition, scoped redirects/downloads, optional local
  token or cookie authentication, and private cookie persistence.
- Encodings, hashes, classical ciphers, XOR, integer/RSA helpers, AES with known
  keys, packing, cyclic patterns, and candidate extraction.
- Bounded static inspection for archives, images, audio, packet captures,
  SQLite, PDF text, Java classes, PE, ELF, and several CPU disassemblies.
- Scoped TCP/TLS service interaction (scripted exchanges and solver pipes) with
  explicit grants, DNS-rebinding refusal, byte/time bounds and saved transcripts.
- Isolated dynamic execution (run/strace/ltrace/gdb/pwntools scripts) in a
  no-network container; challenge programs never run on the host.
- Optional JavaScript rendering with out-of-scope requests aborted.
- Claude Code project skill, `/ctf` command and nine category subagents (including the Blue Team `ctf-blue`)
  (install from `integrations/claude-code/`).
- Official CTFd, rCTF and ksnctf JSON verdicts and explicitly configured HTML-form verdicts; reflected
  candidates and HTTP status alone are rejected as proof.
- Duplicate-answer prevention, rate-limit handling, post-failure hypothesis
  revision, resumable state, and evidence-backed reusable technique cards.
- Six synthetic offline category exercises and a local CTFd-shaped rehearsal
  server for repeatable tests.

Uploaded programs are never executed on the host; dynamic analysis requires a
local container engine. A container is defense in depth, not a proof against
kernel exploits. The image is built for the host CPU; foreign-architecture
targets (x86-64 on Apple Silicon) run through QEMU user-mode, where gdb works via
QEMU's gdb stub, strace via `qemu -strace`, and ltrace is unavailable. Platforms other than CTFd, rCTF and ksnctf need the generic
HTML form verifier or a new adapter.

## Development

Implementation handoff: [CTF tool environment and specialist orchestration design](docs/CTF_ENVIRONMENT_AND_ORCHESTRATION.md)
(Japanese). Read it with `AGENTS.md` before extending category specialists,
subagent execution, or tournament coordination; it distinguishes existing
capabilities from the remaining implementation work. The implemented runtime is
described in [ORCHESTRATION_RUNTIME.md](docs/ORCHESTRATION_RUNTIME.md).

Run `python3 scripts/setup.py --dev`, then `pytest`, `ruff check src tests scripts`,
and `mypy src/metis`. The optional standalone provider/container experiments are
kept for research but are not part of the default solve path. The broader
[master implementation plan](docs/MASTER_IMPLEMENTATION.md) remains a research
roadmap rather than a claim of completion.

Use METIS only for competitions, local fixtures, and infrastructure that the
user is authorized to test. Keep credentials and private flags out of Git and
reusable memory.
