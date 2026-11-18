# Changelog

## Unreleased — Issue #11 (specialist orchestration runtime)

- Typed contracts (`agent_contracts.py`) and deterministic wave policy: `sequential` for simple
  problems, `delegated` with 2-4 distinct roles; category source recorded.
- Host adapters (`bridge`, `sequential`, test `fake`), model selection from the host-reported catalog.
- Scheduler: global/per-run slots, attempts, deadlines and max turns, cancel/retry/release, tool
  intents executed by the controller under a per-run lock (single writer).
- Reports validated as `CompactReport`; `synthesize` adds a versioned `decision`; further waves need a
  resolved wave, budget and a different hypothesis.
- Submissions to one run are serialized; interrupted sends stay `unknown`.
- Contest: run/problem identity check, dispatch timebox.
- Shared resource capacities with atomic whole-set leases (`metis resource`), used by the sandbox
  and headless rendering; exact, expiring, counted permits (`metis permit`); prerequisite cycle
  rejection and `blocked_by_prerequisites` reporting for contests.

## 0.5.0 — 2026-11-16

First version that covers a whole contest from start to finish.

- Launcher `./play`: start screen (contest list and details), tmux session with an
  interactive Claude Code window, a live dashboard and optional swarm workers.
- Contest records: platform, URL and rules (`metis contest new / configure / info`);
  `metis contest refresh` adds only the challenges that are new on the platform.
- Swarm: independent parallel workers (`metis swarm run`), dashboard (`swarm watch`),
  readable per-worker logs, `--tmux` layout, `handoff` state and `swarm handoff --prompt`
  for steps that need the operator's signed-in browser.
- Remote services: `metis remote` (TCP/TLS exchange, pipe, connect, SSH). Endpoints can be
  selected by `host:port` or `latest`, and `grant --replace` revokes old instances.
- Isolated execution: `metis sandbox` (no network, read-only, QEMU for foreign architectures).
- Platforms: CTFd, rCTF, ksnctf and AlpacaHack (browser submission recorded with
  `metis web attest`); download retry and `metis codex add-file`.
- Write-ups and knowledge: `metis writeup` (per-contest Markdown, KNOWLEDGE.md, flag check).
- Claude Code integration, proxy-aware networking, relocatable setup (`scripts/setup.py --all`).
- `metis --version`.

## 0.0.1

Initial Codex-native workflow for single challenges.
