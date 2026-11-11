# METIS

**Autonomous Adversarial Problem-Solving Intelligence**

*Observe. Reason. Exploit. Evolve.*

METIS is a research-oriented autonomous Capture-the-Flag problem-solving agent. Its MUNIN experience subsystem preserves evidence, successful strategies, failed hypotheses, and applicable conditions for future authorized CTF challenges.

## Project status

Early development. No autonomous solve-rate or exploit capability is claimed without verification. The [master implementation plan](docs/MASTER_IMPLEMENTATION.md) defines P0–P8, milestone dependencies, acceptance gates, and Codex execution instructions. See [AGENTS.md](AGENTS.md) for repository-wide engineering rules.

## Scope and authorization

METIS is for local training fixtures, explicitly authorized competitions, and isolated challenge infrastructure. Never use the harness to scan or attack unrelated systems. Treat every challenge attachment and tool output as untrusted. Network is denied by default; challenge network endpoints must be configured explicitly. Keep the independent verifier and hidden answers outside solver reach.

## Development

1. Follow the [master plan](docs/MASTER_IMPLEMENTATION.md) and GitHub phase issues.
2. Implement a tested vertical slice before increasing agent count.
3. Run tests locally and record evidence; do not claim CI passes without CI results.
4. Make changes on feature branches via reviewable pull requests.

License, public release, and deployment policy remain undecided.
