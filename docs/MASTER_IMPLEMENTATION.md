# METIS — Master implementation program

Version: 0.1 | Status: planned | Owner: 01rabbit | Development engine: Codex

**Identity:** METIS — Autonomous Adversarial Problem-Solving Intelligence.
**Slogan:** Observe. Reason. Exploit. Evolve.
**MUNIN:** Memory and experience subsystem; independently testable, no assumed model weight updates.

## Objective and non-goals
Create a fully autonomous CTF agent that ingests a challenge, infers category and hypotheses, picks authorized tools, executes in isolated runners, revises failed hypotheses, verifies a flag through an independent oracle or official competition mechanism, and records transferable experience. Performance is measured on unseen challenges under explicit resource budgets.
Non-goals: general Internet offensive automation, arbitrary target discovery, unsupervised access to external systems, or declaring model fine-tuning from stored examples.

## Design invariants
- No tool execution or network access until scope authorization is validated.
- Solver cannot access evaluator hidden answer store, mutate policy, change its quotas, or edit verification results.
- Challenge statements, user-uploaded archives, retrieved writeups and tool stdout/stderr are untrusted; apply instruction/data separation.
- Use disposable unprivileged sandbox runners; do not mount host credentials, Docker socket, home directory, or broad filesystem trees. Network denied by default. A per-challenge endpoint allowlist is a capability, not a model-supplied string.
- Persist run configurations, artifact SHA-256, model/provider/version, prompts or prompt digests, tool invocations, terminal outputs with secret redaction, costs and termination reasons.
- Require independent positive verification; candidate flag patterns alone do not mean solved.
- Every potentially destructive tool needs a reversible, explicitly approved challenge-only context. Never carry CTF target access beyond permitted environments.
- Repo's implementation and evaluation layers must remain model/provider agnostic.

## System architecture
```text
Challenge Intake -> Authorization/Scope -> Planner/Orchestrator
                                              |-> Specialists (pwn/rev/web/crypto/forensics/misc)
                                              |-> Tool Broker -> Isolated Linux Runners
                                              |-> MUNIN Experience Retrieval
                                              v
                                     Candidate Flag Extractor
                                              v
                       Independent Verifier -> Evaluation -> Experience Publisher
```

Responsibilities:
- **Control plane:** challenge manifest parser, authorization, budgets, lifecycle, safety policy, state transitions, cancellation.
- **Model adapters:** provider-neutral structured messages/tool calls and usage; OpenAI initial implementation, alternative provider stubs supported without framework lock-in.
- **Execution plane:** subprocess/tool adapter in disposable sandbox; no host execution of challenge payloads. Tool approval/scope enforced outside LLM.
- **Domain specialists:** typed capabilities and knowledge; general agent first, then deterministic routing and specialization.
- **MUNIN:** evidence and technique records, applicability constraints, failure analysis, provenance and versioning, retrieval and memory ablation.
- **Evaluation:** oracle isolation, reserved datasets, fixed seeds and budgets, benchmark reports, repeated-trial statistics.
- **Operator UI:** run state, action history, policy events, costs, artifacts, cancellations, read-only default access.

## Data contracts
Minimum entities: Challenge, ChallengeArtifact(hash/size/type), ScopeGrant, Run, Hypothesis(evidence/confidence), Action(tool/args/allowlist/policy decision), Observation(stdout digest/exit status/timing), CandidateFlag, Verification(kind/verdict/oracle provenance), Experience(technique/applicability/negative result/source), EvaluationTrial.
Every entity has stable IDs, timestamps and schema versions; outputs carry content hashes. Keep confidential flags and prompts out of operational telemetry.

Run state machine:
`NEW -> VALIDATED -> CLASSIFIED -> PLANNING -> EXECUTING -> OBSERVING -> {REPLANNING | VERIFYING | HALTED} -> {SOLVED | EXHAUSTED | POLICY_DENIED | ERROR | CANCELLED}`
All transitions persisted as append-only events with idempotent replay; no unbounded retries.

## Phases, dependencies, and gates

### P0 — Foundation (no dependencies)
Deliver: repo packaging, README, AGENTS.md, ADRs, scope authorization policy, threat model, typed manifest/events, fixture format, independent evaluation layout, development setup, static checks, unit test skeleton. macOS Apple Silicon host is a supported *controller*, never an implicit Linux execution sandbox.
Gate: reproducible local setup; schema validation fixtures; denial tests for invalid authorization; independent answer separation proven by tests; initial ADRs and documented risk register.

### P1 — Autonomous Core (depends on P0)
Deliver: `metis run challenge.yaml` and `metis inspect RUN_ID`; provider adapter; budgeted observe-plan-act loop; tool broker; container/VM execution boundary; flag candidates; independent verifier; SQLite+JSONL events; cancellation; at least two simple deterministic local categories.
Gate: fully autonomous solve of at least one locally generated fixture under a real configured model; no credentials in logs; deliberate tool failure cannot crash orchestrator; budget exhaustion terminates; 2 category fixtures pass tests. Report real measured solve rates, do not invent.

### P2 — Specialist Agents (depends on P1)
Deliver Pwn, Reverse Engineering, Web, Crypto, Forensics and Misc specialist interfaces plus tool packs; category router supporting multiple labels and fallback to general solver; tools optional when unavailable.
Gate: contract tests per category, deterministic fixture for each and regression suite with explicit supported/unsupported capability matrix; all tool activity scoped.

### P3 — MUNIN Experience Engine (depends on P1; integrate P2)
Deliver versioned records of successful and failed attempts, extraction of technique cards, SQLite FTS retrieval then optional embedding retrieval, applicability checks (architecture, library versions, protections, protocol), provenance, curation, retrieval filters by benchmark split.
Gate: at least one cross-challenge transfer exercise on non-identical fixtures, no evaluation-answer leakage, retrieval ablation results and reproducible records.

### P4 — Adaptive Reasoning (depends on P1+P3)
Deliver hypotheses ranked by evidence, contradiction tracking, novelty-aware actions, stuckness detection, alternative-plan generation, bounded lookahead, reproducible cost-aware policy.
Gate: a known dead-end fixture triggers a distinct strategy; same failing action is not repeated blindly; fixed-budget benchmark comparison with baseline and error bars.

### P5 — Multi-Agent Orchestration (depends on P2+P4)
Deliver bounded parallel specialists, delegated tasks and scoped capabilities, controlled shared observations, conflict adjudication, state reconciliation, cancellation and deterministic serialization of decisions.
Gate: parallel run never exceeds global budget and authorization, race-condition tests, at least one demonstrable win against single-agent baseline without leaking oracle data.

### P6 — Autonomous Research (depends on P3+P5)
Deliver experiment proposals for local challenge fixtures, hypothesis-testing scripts, synthetic challenge family generation, reproducible evaluation of reusable workflows and human-reviewed publication of tool extensions.
Gate: generated workflows are tested in sandbox; tool additions require explicit maintainer review; no self-modification of policy/verifier or deployment permissions.

### P7 — Competitive Evaluation (depends on P1–P6)
Deliver held-out benchmark manifest and hidden oracle, categories/difficulty strata, repeated trials with pinned model configurations, ablations (without MUNIN, without planner, single vs multi-agent), cost/time/solve metrics and confidence intervals, contamination checks.
Gate: reproducible report using unseen problems, verified flags only counted solved, cost and runtime recorded, no unjustified “best” claim. Publish failure analysis.

### P8 — Production Harness (depends on P7)
Deliver secure Web UI/API, immutable run evidence and artifact lifecycle, operator pause/cancel, quotas, role separation, release packaging, reproducible deployment on Apple Silicon macOS controller with Linux execution VM, CI and runbooks.
Gate: end-to-end installer smoke test on target platform; policy boundary penetration tests; operator recovery drills; benchmark regression gate; documented limitations.

## Engineering issue plan
Use GitHub issues titled `[P0]` through `[P8]`, each with deliverables, tests, dependencies, acceptance gate and evidence location. Break phases into implementation subtasks after the initial working vertical slice. Keep blocked items open, never silently mark complete.

## Release checkpoints
- `v0.1`: P0/P1 vertical slice, isolated local fixtures.
- `v0.2`: specialists and MUNIN, demonstrated transfer.
- `v0.3`: adaptive strategy and multi-agent orchestration.
- `v0.4`: research and scientifically valid evaluations.
- `v1.0`: hardened operator environment and measured, reproducible capability.
Versions denote targets, not claims of delivery.

## Suggested repository shape
```text
src/metis/{cli,core,models,tools,sandbox,agents,munin,verification,evaluation,api}
configs/  docs/adr/  docs/reports/  schemas/
challenges/training/  challenges/development/  challenges/evaluation/
tests/unit/  tests/integration/  tests/security/  scripts/
```
Evaluation answers must be stored outside any agent-visible project tree during execution. Do not ship challenge secrets in tracked fixtures.

## Default operational budgets
Define configurable bounded defaults, e.g. maximum actions 40, challenge wall time 20 minutes, per-tool wall time 30 seconds, max parallel workers 2, capped LLM token and monetary budget. These are initial policy values to be tested, not universal recommended limits. The orchestrator enforces all upper bounds independent of model responses.

## Quality and quantitative performance
Metrics: verified solve rate, fully autonomous completion rate, median/percentile time to verified flag, model/tool spend per verified solve, policy violations (must be zero), stalled-run fraction, memory transfer delta and variability. For comparisons, keep identical model, token budget, tool images and challenge selection; use repeated randomized run ordering and report confidence intervals. Keep training/development/held-out sets distinct.

## Codex execution directive
Read AGENTS.md and this plan. Audit repository status and pre-existing issues first. Implement P0 through P8 in dependency order, but do not skip tests or declare unsupported success. Start with a minimal fully functioning isolated solver; write code and tests, document actual command outputs, and open small reviewable PRs. Record issues for blockers, continue unblocked work, and give a truthful summary of changes and metrics. Never ask an LLM to decide its own permissions.
