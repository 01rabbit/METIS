# Issue #6 paired scheduler benchmark (2026-11-17)

## Question and scope

This deterministic micro-benchmark measures the scheduler's ability to run
independent specialist work in parallel under the same controller budgets. It
does not measure model reasoning, token usage, monetary cost, or real provider
wall-clock latency.

## Paired protocol

Thirty seeded local tasks each contain two independent encoded byte fragments.
Their order alternates between Base64 and hex, using seed `20261117`. Each arm
gets a separate METIS run with the same registered artifacts, action limit
(four, of which two are used), shared wall-clock budget (300 seconds), and
per-run model-turn cap (two). The private `FixtureOracle` is a mode-0600 file
outside every run's artifact root; only the controller-side evaluator loads it.
The deterministic service model is fixed before measuring outcomes: each
worker requires one fake-host poll per assigned model turn, regardless of how
many artifacts it receives.
The scheduler enforces each explicit `inputs.artifacts` assignment: only its
listed artifact names appear in that worker's brief, artifact/derive/view
intents outside the set are rejected, and reports cannot reference artifacts
outside the set. A successful derived artifact is added only to the creating
assignment's scope. The two-agent arm uses disjoint, registered subsets; the
single-agent arm receives both artifacts.

- **Single-agent baseline:** one generalized assignment decodes both artifacts
  sequentially, reserving two model turns and making two controller-mediated
  artifact intents.
- **Multi-agent arm:** two distinct specialist assignments start together and
  each handles one artifact in a single simulated provider round, reserving one
  model turn and making one artifact intent apiece.

Both arms use the same generic decoding procedure. A deterministic `FakeHost`
worker reads only its assignment's artifact subset and itself uses production
`AgentScheduler.reserve_model_turn`, `intent`, and `complete` paths. The test
driver dispatches jobs, advances scheduler ticks, and scores the decoded
fragments. Both arms pass reports through `AgentLedger.synthesize`. The test
checks that both syntheses are complete, each run reserves
exactly two turns and two tool actions, and the controller-combined result is
verified by the private oracle. Reports cite actual observation events and do
not contain the final candidate; the candidate and oracle path are absent from
persisted events and reports.

## Results

| Measure | Single-agent baseline | Multi-agent arm |
| --- | ---: | ---: |
| Oracle-verified tasks | 30/30 | 30/30 |
| Reserved model turns per task | 2 | 2 |
| Tool actions per task | 2 | 2 |
| Simulated serial provider rounds per task | 2 | 1 |
| Total simulated rounds | 60 | 30 |

The scheduler model completes all tasks in both arms. It reduces the simulated
serial provider rounds by 50% because the two specialist assignments are
dispatched in one batch. These rounds are deterministic `FakeHost` poll units,
not measured elapsed seconds. Under the stated one-poll-per-turn model,
`AgentScheduler.tick` polls the fake workers
serially, so this does not measure real tool-call concurrency or latency. The
workers use a fixed deterministic policy, not model output, and therefore
cannot show a model solve-rate advantage. A confidence
interval would be misleading for this fixed latency model, so none is reported.

Reproduction:

```text
.venv/bin/pytest -ra tests/test_agent_benchmark.py
1 passed in 2.40s
.venv/bin/ruff check tests/test_agent_benchmark.py
All checks passed!
.venv/bin/pytest -ra tests/test_intent_identity.py tests/test_agent_benchmark.py tests/test_agent_orchestration.py
31 passed in 4.19s
.venv/bin/ruff check src/metis/core/agent_scheduler.py src/metis/core/ctf_orchestration.py tests/test_intent_identity.py tests/test_agent_benchmark.py
All checks passed!
.venv/bin/mypy src/metis
Success: no issues found in 52 source files
.venv/bin/pytest -ra tests/test_intent_identity.py tests/test_agent_benchmark.py tests/test_agent_orchestration.py tests/test_agent_autopilot.py tests/test_codex_specialist.py tests/test_ctf_x509.py
74 passed, 1 skipped in 8.01s
```
The single skipped regression requires the external ksnctf #33 capture in
`METIS_TEST_KSNCTF33_PCAP`; assignment-scope and race tests use generated local
artifacts. Intent admission, turn-cap reservation, and action identity reservation
use the short per-run state lock. Tool execution uses a separate cancellable
per-run operation lock, so cancellation and deadlines can stop a sandbox worker
without waiting for the tool's bounded timeout. Results and derived-scope updates
are committed only after rechecking the assignment attempt and deadline. Each
action carries its exact observation sequence through commit, so interleaved
intents cannot cite another action's event. Concurrent calls cannot exceed a job
turn cap; canceled or late results are discarded. A real
Docker integration test verifies cancellation removes a running long-lived sandbox
worker and does not commit its observation or action.

## Limitations

This establishes a narrow scheduler/concurrency mechanism result with matched
turn and tool-action caps. It does not establish that specialist models solve
more tasks, use fewer tokens, or have lower real-world latency than a single
agent. BridgeHost-native calls remain outside METIS's call reservation
boundary. The fake workers' scheduler calls are advanced serially within each
tick, and a controlled matched-budget comparison with a real model is still needed;
Issue #6 remains open.
