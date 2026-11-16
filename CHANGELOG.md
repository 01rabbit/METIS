# Changelog

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
