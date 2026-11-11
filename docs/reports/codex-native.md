# Codex-native working slice

The user clarified that Codex hosts the agent itself. The new default is the
repository METIS skill plus `metis codex`, not an independently hosted model loop.
There are no API calls, Docker operations or challenge program execution in this
backend. Only three bounded builtin data transforms run on the host.

Actual demonstration in this Codex session:

| Puzzle | Codex-selected tool | Controller verdict |
| --- | --- | --- |
| Generated crypto data | base64_decode | verified, solved |
| Generated misc data | hex_decode | verified, solved |

Codex read each problem statement, selected and called the tool, inspected the
observation, and submitted the returned candidate through stdin. It did not use
FixtureProvider, an external model API, Docker, or a plaintext oracle store.
The pre-existing SHA-256 commitment verified the result. This is an actual local
data-puzzle demonstration, not a benchmark of unseen CTF problems.

Four dedicated tests cover both demos with subprocess creation forbidden for
the native backend, rejected candidates, no plaintext answer persistence,
terminal-state enforcement, scope rejection, budgets, cancellation, bounded
invalid inputs and real CLI invocations across processes. Full-suite results:
90 passed, 8 optional Docker cases skipped due to missing cgroups. Ruff and mypy
passed (14 source files). The native path is usable despite those optional skips.

Limits: native commands do not execute challenge binaries, read artifacts or
contact endpoints. Supplied inline puzzles without a trusted answer commitment
can produce only unverified candidates. A host/database owner can tamper with
state; no hostile-agent isolation or complete P0–P8 delivery is claimed.
