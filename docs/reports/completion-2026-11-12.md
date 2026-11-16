# Completion increment: remote services, sandbox, platforms, Claude Code

Date: 2026-11-12

## Added

| Area | Module / files | CLI |
| --- | --- | --- |
| Remote TCP/TLS services | `src/metis/core/ctf_remote.py` | `metis remote suggest/grant/exchange/pipe` |
| Dynamic sandbox | `src/metis/core/ctf_sandbox.py`, `sandbox/Dockerfile` | `metis sandbox status/build/configure/run` |
| rCTF adapter | `src/metis/core/ctf_rctf.py`, `ctf_web.py` | `web auth --kind rctf-team-token`, `web catalog/open --adapter rctf` |
| JavaScript rendering | `src/metis/core/ctf_browser.py` (optional `browser` extra) | `web open --render` |
| Claude Code | `integrations/claude-code/` (copy into `.claude/`), `CLAUDE.md`, `start` | `./start --agent claude`, `/ctf` |

Supporting changes: `CodexSession.store_artifact()` (shared by `derive`, remote
transcripts), `network_tools` in run context lists granted endpoints, triage
playbooks and `remote_service_hint`, `doctor` reports sandbox/rendering/adapters,
`scripts/setup.py --browser`.

## Observed validation

- `pytest`: 229 passed, 10 skipped (8 pre-existing Docker fixture tests, the
  opt-in real sandbox and browser tests when their variables are unset).
- With `METIS_TEST_SANDBOX_IMAGE` and `METIS_TEST_BROWSER` set, both opt-in
  tests passed against a real Docker daemon and Chromium.
- `ruff check src tests scripts` and `mypy src/metis`: clean, with and without
  the `browser` extra installed.
- Real Docker run of a compiled test binary through `metis sandbox run`:
  normal run with stdin, SIGSEGV reported as signal 11, `strace` trace returned,
  `gdb` batch showed the overwritten return address (`0x4141414141414141`),
  script mode ran the target, observed `Network is unreachable`, read-only
  root, and uid 65534; no containers remained afterwards.
  gdb printed "Error disabling address space randomization" (expected without
  capabilities); this does not prevent debugging.
- Real TCP quiz service (local test server): scripted exchange and solver pipe
  both obtained the success token; run events contained only digests.
- Real headless Chromium: a JavaScript-built page rendered, and a third-party
  image request was aborted and reported as a blocked origin.

## Not validated here

- Building `sandbox/Dockerfile` (container registries were unreachable in the
  validation environment; the run used a locally imported test image). Build it
  with `metis sandbox build` on the target machine.
- Podman and live rCTF/CTFd events.

## Follow-up on the user's Apple Silicon Mac (OrbStack)

- The bundled Dockerfile built successfully (linux/amd64) and the real sandbox
  isolation test passed there.
- Under Rosetta, ptrace failed (`PTRACE_GETREGS: Input/output error`), so gdb,
  strace and ltrace did not work in an x86-64 image.
- Fix: images now build for the host CPU, and foreign-architecture ELF targets
  run through QEMU user-mode with cross libcs; gdb attaches via QEMU's gdb stub.
  Validated here in the mirrored configuration (amd64 image, arm64 target) with
  real Docker: run, strace (35 syscall lines), gdb breakpoint/registers/
  disassembly, and script mode via `$METIS_RUNNER`.
- Also fixed: `metis codex intake` rejected explicit paths under symlinked
  directories such as macOS `/tmp`.
- Claude Code subagent dispatch itself (files are checked for structure only).
- Confirmed on the user's Apple Silicon Mac (OrbStack, linux/arm64 image): an
  x86-64 ELF was detected and run under `qemu-x86_64` automatically; gdb mode
  stopped on SIGSEGV with `rip = 0x4141414141414141` and read the stack.
- Dockerfile: ltrace (not packaged for arm64 in bookworm) and cross libcs are
  now optional; sandbox CLI errors state the real cause (engine not running,
  build exit status).

## Follow-up 2026-11-13: Claude Code run on ksnctf

Observed in the METIS state after an unattended Claude Code session: 26 of 41
ksnctf problems officially solved, then the session stopped. Causes and fixes:

- Raw sockets and local DNS are blocked in the Claude Code sandbox, so
  `metis remote` failed with `gaierror` even for allowlisted hosts. Remote
  connections now tunnel through the sandbox proxy (SOCKS5 or HTTP CONNECT).
  Tested with local SOCKS5 and CONNECT proxies while local DNS was disabled.
- No HTTP interaction existed for challenge web servers, so the agent created
  extra `web open` runs and hand-wrote HTTP over a TLS pipe. Added
  `metis web grant` and `metis web request` (batched, shared cookie jar).
- SSH problems had no client path. Added `metis remote ssh` (command, stdin,
  SFTP download, host-key pinning) and `metis remote connect`.
- All 41 runs were opened at once and their two-hour clocks expired together;
  the agent reopened problems as new runs. The clock now starts at the first
  action, and `metis codex extend` resumes a budget-exhausted run.
- No technique cards and no contest board were recorded; the Claude Code
  skill now requires both and describes resuming from METIS state.
