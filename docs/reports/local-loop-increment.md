# Local-fixture loop increment

Implemented: typed provider decisions/context, a deterministic fixture planner,
an optional fixed-destination OpenAI JSON adapter, controller-owned budgets,
bounded plan/act/observe/verify orchestration, explicit terminal states,
repeated-action detection, between-call cancellation and private local oracle
verification. CLI generates two synthetic categories and runs/inspects them.
Development dependencies are pinned by uv.lock; CI uses locked installation.

Functional CLI trials before the quota capability check:

| Category | Provider | Verdict | Seconds including inspection | Events | Failed tool observations |
| --- | --- | --- | --- | --- | --- |
| crypto | deterministic fixture | local oracle accepted | 6.775 | 16 | 1 |
| misc | deterministic fixture | local oracle accepted | 4.028 | 12 | 0 |

These two trials are generated puzzles, not unknown CTF problems, and are not
evidence of live-model performance, general solve rates or resource isolation.
The crypto fixture deliberately fails a hex transform before Base64 decoding.
Candidates are accepted only by the external private fixture answer mapping;
the solver context contains neither that mapping nor its path. Events contain
only status, fixed reason codes, counts, elapsed time and reserved usage.

Late environment review found rootless Docker without cgroup delegation:
`CgroupDriver=none`, cgroup version 2. Requested CPU/memory/PID flags alone did
not prove enforcement. The hardened runtime refuses this state and additionally
checks actual cgroup files before executing transforms. There is no unsafe
fallback. Current results: 86 tests passed, 8 Docker cases skipped for that
documented blocker; those cases are required/failing rather than skipped in CI
if resources are unavailable. No remote CI result is claimed.

Model adapter tests use synthetic credentials and an in-memory HTTP stub; they
make no network request. No actual model call or billing has occurred. The
environment draft now saves installation/start instructions, a pinned test image,
and a METIS_OPENAI_API_KEY requirement restricted to api.openai.com. The value
must be entered securely and changes saved/published by the user. The running
instance has neither model binding. Draft saving is not runtime application.

Limits: a trusted in-process adapter/controller can access host data, so arbitrary
Python adapters are not a security boundary. The actual model is constrained by
typed messages, fixed tools and a separate controller. A controller compromise,
malicious images, kernel escapes, safe general binary execution, execution resume,
current-price validation, official verifier APIs, held-out benchmarks and macOS
deployment remain unvalidated/unimplemented. P0/P1 gates and later phases remain
open. No issue closure or empirical improvement is claimed.
