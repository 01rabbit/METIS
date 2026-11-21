# CTF readiness pass under Claude Code (2026-11-21)

Local branch `local/integration-2026-11-21` (not pushed). Base: `origin/main`
`06596ce`, plus the pushed candidates `codex/issue8-llama-cap-probe` (with the
review fix `07defb1`) and `codex/issue6-scheduler-preflight`.

## Purpose and scope

Make METIS usable for a live CTF from Claude Code on macOS (Daybreak plus the
`ctf-*` subagents), and record what was checked. This is operator-readiness work.
It is not an Issue #6–#9 acceptance result: no real-model study, held-out
benchmark, platform submission or release was run.

## Method

1. Seven read-only audits by lower-tier subagents: Claude Code integration docs
   against the CLI, local-file E2E, web intake/submit, `nc` remote, `metis
   sandbox`, contest/swarm/writeup/memory, and Claude Code Bash-sandbox friction.
2. Fixes and features in isolated worktrees, merged here, then re-verified
   outside the Bash sandbox (port-binding tests need it).
3. Rehearsals with the real workflow: practice runs with `--expected-sha256`,
   `metis plan --mode delegated`, `metis agent dispatch`, the matching project
   subagent per brief, `agent synthesize`, and local `codex submit`.
4. A read-only live intake of `https://ksnctf.sweetduet.info/problem/1` (no
   submission) into a separate database.

## Changes

| Area | Change |
|---|---|
| CTFd | Out-of-scope file redirects are skipped per file with an `--allow-origin` hint instead of aborting `open`; HTML login pages are reported as authentication required; `paused` is retryable and `partial` is recorded unsolved; cookie-auth submits send the `csrfNonce` as `CSRF-Token`; `connection_info` reaches the run description; the catalog truncates at 500 with `truncated`, `type` and `solved`. |
| Remote | `connect --idle-timeout` (default 10 s) and socket/stdout error handling that still emits the result; non-blocking solver stdin in `pipe`; per-endpoint opt-in `grant --tls --tls-insecure [--sni]`; grant warns for private hostnames; `suggest` recognises socat, openssl, telnet and bare `host:port`. |
| Artifact tools | `carve`, `flag_scan`, artifact `xor` / `xor_single`, `base64_decode {"extract":true}`; TCP reassembly `pcap_streams`, `pcap_stream`, `http_objects`; `rsa_decrypt` accepts `n` plus one factor; `disassemble` takes the architecture from the ELF header. |
| Operator errors | Artifact/derive failures carry a bounded `detail`; unknown options are named with the accepted keys; `codex tools` lists each tool's inputs/options; inline-tool input errors give a tool-specific example; `codex submit` strips one trailing newline like `web submit` and returns a `reason`; `codex recover` says when the container engine was unreachable. |
| Orchestration | Briefs carry `intent_examples` and a `report_template`; memory cards are filtered by the planner's triage category when intake declared none; triage uses artifact magic before keywords (an ELF crackme was planned as misc); `metis sandbox` refuses before reserving when the engine is unreachable; agent instructions require the repo root and bare sandbox calls; `contest claim` takes dispatched-but-unowned challenges; specific reasons from `memory learn`, `writeup save` warnings, `plan` next hints. |
| Development under the Bash sandbox | `setup.py` retries `uv sync` once with bundled certificates on `invalid peer certificate`; `check_repo.py --allow-unreadable`; pytest skips only OS-unreadable paths; `sandbox status` hints at the Claude Code sandbox for docker-socket permission errors. |
| Docs | Write-up JSON schema inlined in the skill; live contest recipe in `docs/TOURNAMENT_MODE.md`; nc-only intake recipe; skill notes for the new tools, TLS grant options, and the bare-command rule for `metis sandbox`. |

Issue #6 retrospective analysis: `docs/reports/issue6-failure-breakdown-2026-11-21.md`.

## Verification

- Full suite outside the Bash sandbox at `f9488b0`: 2175 passed, 40 skipped,
  1 failed (`.venv/bin/python -m pytest -q`). The failure,
  `test_ctf_web_request.py::test_remediation_and_environment_mode_recheck_paths_after_open[-wal-WAL]`,
  passed in 3 isolated runs and 5 runs of its file; neither the test nor its code
  path changed on this branch, so it is recorded as an existing timing-dependent
  flake around the SQLite WAL sidecar. At `420d2d1` the suite had 2145 passed,
  0 failed. `ruff check src tests scripts`, `mypy src/metis`
  (120 files) and `scripts/check_repo.py` (0 findings) pass.
- `metis sandbox` on this machine (OrbStack, linux/arm64 image
  `sha256:2509ca19…`): run with stdin, script mode, network blocked, uid 65534,
  gcc/gdb/strace present. A `ctf-rev` subagent reached it as a bare command.
- Rehearsal 1 (forensics: PNG with an appended ZIP whose member is single-byte
  XOR; crypto: two RSA moduli sharing a prime): both runs reached `solved` via
  local verification. Triage and forensics subagents produced correct reports
  but needed 7 retries guessing the intent/report contracts, which led to the
  brief templates; the critic, given the templates, had no contract errors.
- Rehearsal 2 (rev: stripped aarch64 ELF password checker built inside the
  sandbox): `solved` after Daybreak confirmed the candidate with `metis sandbox
  run` (`correct!`) and local verification. The `ctf-rev` subagent recovered the
  check (length 19, byte-wise XOR with a 4-byte mask, table offsets) but did not
  finish reading the table. Findings fixed on this branch: the plan picked a
  misc specialist (keyword-only triage), `disassemble` defaulted to x86_64 on an
  aarch64 ELF, a subagent sandbox call hit an intermittently blocked engine and
  left the run needing `codex recover` (now refused before reservation), `codex
  recover` hid the cause, the credential filter rejected a quoted `'password: '`
  prompt, and running `metis` from another directory missed the relative
  database.
- Rehearsal 3 (pwn: aarch64 ELF where `fgets` overruns a 32-byte name into an
  adjacent role field): planned as `pwn` with a declared category (keyword
  triage now also puts pwn first for a binary with exploitation words). The
  `ctf-pwn` subagent found the bug and payload layout and wrote a pwntools
  script; its own sandbox call met the intermittently blocked engine and was
  refused before reservation with the new message, so it handed off as
  instructed. Daybreak ran the script with `metis sandbox run --mode script
  --with 01-fakeflag.txt`, which printed the admin branch with the local stand-in
  flag. No service was granted, so the real flag was not retrieved or submitted.
- `--database` is now accepted before or after the subcommand for every group
  that has it.
- Live intake of ksnctf problem 1 created a planning run with the problem page
  artifact; nothing was submitted.

## Known limits

- Claude Code's Bash sandbox blocks local port binding, the docker socket for
  non-bare commands, the macOS keychain (`gh`), and any path matching
  `*credential*`. Four tracked files match; they were not renamed because Blue
  Team knowledge digests reference them.
- The action budget still charges rejected tool calls; changing it touches the
  append-only ledger and audit accounting.
- `flag_scan` decodes only whole-artifact layers; carve or derive embedded blobs
  first. pcapng support is limited to enhanced packet blocks with one link type.
- Subagent Bash calls to the docker socket fail intermittently even as bare
  `metis sandbox` commands; Daybreak's own calls have worked. Plan for Daybreak
  to run dynamic steps when a worker reports the engine unreachable.
