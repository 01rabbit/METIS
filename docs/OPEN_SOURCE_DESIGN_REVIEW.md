# Open-source CTF agent design review

Reviewed 2026-11-12 at the pinned commits below. METIS adopts bounded design
patterns; it does not vendor these projects or execute their tooling.

| Project | Reviewed commit | License relevant to review | Pattern used |
| --- | --- | --- | --- |
| [NYU D-CIPHER](https://github.com/NYU-LLM-CTF/llm_ctf_automation) | `612190f` | MIT | Planner delegates a focused task to a fresh executor; only a compact completion summary returns. Structured failures remain observations and wrong flags do not end the loop. |
| [Buttercup](https://github.com/trailofbits/buttercup) | `298c01f` | AGPL-3.0 | Explicit workflow state, layered independent gates, duplicate-attempt detection, and failure-specific reflection routing. Ideas only; no code copied. |
| [CAI](https://github.com/aliasrobotics/cai) | `6dc7925` | mixed MIT/research-restricted | Breadth-first specialists, competing approaches, bounded parallel tools, and compact handoff context. Ideas only; no restricted code copied. |
| [HackSynth](https://github.com/aielte-research/HackSynth) | `48a41f7` | AGPL-3.0 | Planner/observation/summarizer loop and benchmark accounting. Ideas only; no code copied. |

The independently implemented `metis codex plan RUN_ID` command expresses the
D-CIPHER planner/executor pattern. It creates two to four distinct assignments,
gives each a bounded turn count and no-history context policy, and requires
compact evidence. Subagents cannot submit flags or expand scope; Daybreak
synthesizes their reports and owns official verification.

METIS deliberately does not adopt unrestricted shell execution, plaintext
answer access, provider API dependencies, or Docker requirements from the
reviewed systems. Its scoped HTTP client, static artifact parsers, official
verifier, hypothesis ledger, and MUNIN memory remain the control plane.
