# Issue #6 autopilot outcome metrics (2026-11-20)

`metis agent autopilot` counts each specialist driver result in the invocation
that collected it. The returned `metrics.specialist_outcomes` and the SQLite
`agent_autopilot_runs.specialist_outcomes` JSON column use the fixed specialist
categories. `none` denotes a classified completion. `driver_exception` counts
raised futures, which still require the existing reconciliation path.
`missing_or_invalid_category` covers absent or unrecognized category values.
Driver exception text, free-form results and candidate values are excluded
from this metric.

New invocations with no started specialist futures record `{}`. Older rows
retain SQL `NULL` for the new column. The counts cover futures collected by a
completed autopilot invocation. They exclude dispatch failures before a driver
starts and work from before the invocation. An interrupted process may leave
no invocation row. A count does not independently verify worker termination,
provider usage, or oracle correctness.

Deterministic tests cover mixed completion and driver exceptions, category
allowlisting across batches, and migration of earlier invocation rows. The
change adds diagnostics for future studies. Issue #6 still requires a
preregistered symmetric comparison showing measured gain.
