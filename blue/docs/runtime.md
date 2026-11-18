# Runtime and state

METIS has two operating modes sharing one contract and one skill library.

- **Native owner**: a Codex/Claude main agent controls user interaction and browser actions,
  claims tasks in SQLite, dispatches its runtime's native workers, then records their results.
  Workers can use connected resources within the granted scope and resource lease.
- **CLI owner**: `run` makes one planning call, runs read-only CLI analysis workers and makes
  one synthesis call. `--plan` replaces the planning call with a reviewed DAG. Claude workers
  have Read/Glob/Grep/WebFetch/WebSearch tools and no MCP servers. Codex workers use its
  read-only sandbox. Neither backend bypasses runtime approval controls.

Provider account quotas, tool ceilings and memory availability cannot be inferred reliably
from a model name. The owner declares them. `--workers` intersects `--provider-limit`, CPU
count and the optional memory limit accepted by `available_workers`. Reserve independent
resource capacities for expensive services. Native workers must use the same `claim` contract.
A prompt declaring a resource is not an OS security boundary; use service-side quotas too.

## Native dispatch example

```bash
metis blue prepare 'Investigate supplied evidence' --plan examples/offline-plan.json
metis blue claim RUN_ID
# Dispatch the returned task with its skill and evidence references using the runtime's agent tool.
# Save the worker's evidence-backed answer under .state/ or logs/.
metis blue finish RUN_ID TASK_ID --result-file .state/result.txt
metis blue close RUN_ID
```

`prepare` with a plan does not launch a model. `claim` is owner-only and atomically selects the
oldest eligible task whose full resource set fits. It skips a waiting task if a later independent
task can proceed. The owner refills free workers continuously and attaches dependency results.
`finish` stores the result and releases the leases. `close` requires no pending/running tasks.
The CLI owner uses the same store automatically. Multiple runs sharing a database also share
resource limits. Separate databases deliberately do not share those limits.

## Persistence and recovery

Tasks move pending → running → done/failed/blocked/cancelled. A failed dependency blocks its
children. An owner exit or crash does not silently expire leases. Pending work can resume with
`metis blue resume RUN_ID --provider ...`. For a stale running task, first verify the actual
local process and remote operation have stopped, then use `finish --state cancelled` with a
recovery note. Never reclaim merely because a deadline passed. Never retry uncertain writes
without reading their actual outcome. Completed tasks are not replayed during resume.

CLI child processes have time limits and are terminated as a process group before releasing
their slot. Jobs started outside that process tree need owner reconciliation. Automatic
connection processes are bounded by `connect --timeout`; persistent sessions should remain
under owner control, retaining their lease until closed.

## Permission boundary

The owner capability is a random private value stored under `.state/private/`. Broker APIs verify
it before configuration, dispatch, finishing or issuing grants. A grant is exact, expiring and
use-limited. It is authority from the existing user instruction, not authority invented by the
model. Workers cannot mint a grant via the public broker without the owner capability.

Same-user Python processes can read each other's files and SQLite. Therefore these capabilities
prevent accidental role confusion, not a hostile local worker. For hostile-input processing,
use separate OS identities/containers, read-only evidence mounts, read-only service accounts,
network policy and a broker reachable only through its narrow API. A filesystem read-only
sandbox alone does not make external network APIs read-only. Direct browser/MCP actions remain
subject to the host runtime and owner policy. METIS does not claim to enforce arbitrary tools.

## Cost and context

Log observable messages, tool records and provider-reported token usage. Do not infer usage
from text length or the UI context meter. Input/cache/output are separate accounting buckets.
Model prices, hidden thinking and network work are not inferred. Native agents are imported
from explicitly named transcript files; import parent and child sessions once under distinct
agent IDs. A provider's parent aggregate that already includes children must not be combined
with the children's totals. Keep one accounting source per actual inference stream.

Missing or explicitly null token fields stay JSON `null` and appear as `unknown` in the
viewer. Only a reported integer zero appears as 0. Each actual CLI/Ollama invocation starts
one usage record with unknown counts, then updates that record when metrics arrive. A failed
or unmetered second call on the same task cannot disappear behind the first call's counts.
Repeated transcript snapshots of one message are merged by its ID; final Claude aggregate
usage replaces message sums, and native Codex cumulative usage uses the last supplied total.
Reimporting the same transcript replaces that source atomically instead of adding it again.

`input_total` is the prompt count including cached input. Codex/Ollama provide that total;
when cache reads are unknown, the noncached `input` component also stays unknown. Claude
reports noncached input, cache reads and cache creation separately, so all three are needed
to derive its prompt total. Cache creation is not reported separately by the supported
Codex/Ollama formats and remains unknown. Never add `input_total` to its component counts.
`total` is `input_total + output` when both are known. This preserves a measured overall
count even when its cache breakdown is unavailable.

`totals` propagate an unknown constituent; they are not sums treating missing values as 0.
`known_subtotals` retain only observed values and can cover different subsets for each field.
Do not combine those partial subtotals into a complete total. Coverage reports distinguish
`total_complete` from `complete` accounting breakdown, and identify missing, synthetic and
legacy agents plus events with unknown fields. Synthetic fixtures contribute no measured
token count.

Opening a database from the older non-null accounting schema migrates the usage table in
one transaction. Original numeric values and event identities remain stored with
`legacy-defaults-unknown` provenance and are available as `legacy_usage` in the report.
They are excluded from measured totals and known subtotals: a historical zero may have been
invented by the old missing-value default. Migration does not reinterpret old exports or
claim those stored values were verified. Reopening is idempotent; an explicit reimport from
an original provider transcript can replace that source with newly normalized observations.

The owner can explicitly resize a resource with `metis blue capacity RUN_ID RESOURCE UNITS`.
This is audited and rejects reductions below active reservations. It changes dispatch capacity,
not the provider/service quota itself.
