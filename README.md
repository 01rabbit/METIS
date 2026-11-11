# METIS

**Autonomous Adversarial Problem-Solving Intelligence**

*Observe. Reason. Exploit. Evolve.*

METIS is a research-oriented autonomous Capture-the-Flag problem-solving agent. Its MUNIN experience subsystem preserves evidence, successful strategies, failed hypotheses, and applicable conditions for future authorized CTF challenges.

## Project status

### Use METIS inside Codex

Codex itself supplies the reasoning. **No API key or Docker is required** for
the Codex-native local-puzzle workflow.

Tell Codex: **“METISでローカルデモを解いて”**, or provide an authorized inline
challenge manifest. Codex follows the repository's [METIS skill](.agents/skills/metis/SKILL.md).

To create two immediately runnable demo puzzles:

```sh
uv sync --locked --extra dev
.venv/bin/metis codex --database /tmp/metis-codex.sqlite demo
```

The result contains two run IDs and their problem statements. Codex chooses and
calls `act RUN_ID base64_decode|hex_decode|sha256`, examines the observation, then
uses `submit RUN_ID` with the candidate on stdin. A pre-existing local answer
commitment verifies the result. `context RUN_ID` restores session context and
`cancel RUN_ID` stops it. All commands use the same `codex --database ...` prefix.
The current native tools handle inline local data puzzles; they do not execute
challenge binaries or contact targets. The standalone model/Docker experiment
below is optional and does not block this workflow.

Early development. No autonomous solve-rate or exploit capability is claimed without verification. The [master implementation plan](docs/MASTER_IMPLEMENTATION.md) defines P0–P8, milestone dependencies, acceptance gates, and Codex execution instructions. See [AGENTS.md](AGENTS.md) for repository-wide engineering rules.

## Scope and authorization

METIS is for local training fixtures, explicitly authorized competitions, and isolated challenge infrastructure. Never use the harness to scan or attack unrelated systems. Treat every challenge attachment and tool output as untrusted. Network is denied by default; challenge network endpoints must be configured explicitly. Keep the independent verifier and hidden answers outside solver reach.

## Development

See [Development and current CLI](docs/DEVELOPMENT.md) for installation, checks,
fixture preparation and read-only run inspection.

1. Follow the [master plan](docs/MASTER_IMPLEMENTATION.md) and GitHub phase issues.
2. Implement a tested vertical slice before increasing agent count.
3. Run tests locally and record evidence; do not claim CI passes without CI results.
4. Make changes on feature branches via reviewable pull requests.

License, public release, and deployment policy remain undecided.
