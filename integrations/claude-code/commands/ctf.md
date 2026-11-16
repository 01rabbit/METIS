---
description: Start or continue a METIS CTF solve for an authorized problem URL, nc endpoint, or local files
argument-hint: <problem URL | file paths | run ID> [notes]
---

Use the `metis` skill (`.claude/skills/metis/SKILL.md`). The user authorizes the
following CTF input for analysis and official submission:

$ARGUMENTS

If it is a known run ID, resume it with `metis web context` / `metis codex context`.
Otherwise run `.venv/bin/metis doctor`, take the input into one canonical run,
create a `metis plan` wave, delegate to the `ctf-*` subagents in parallel, and
continue autonomously through official verification and technique learning.
Ask once, in Japanese, only for scope or authentication you cannot infer.
