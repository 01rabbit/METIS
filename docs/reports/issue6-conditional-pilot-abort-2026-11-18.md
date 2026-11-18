# Issue #6 first conditional pilot: aborted design

The initial 12-cluster conditional pilot was committed as `c3336b3` before
model calls. Its runner gave the lead `max_turns=4`, assuming this reserved
four model calls. In the scheduler this field limits mediated actions. The
lead could spend all four run actions before the controller considered a
second wave. A real conditional arm did so and had no completed candidate;
`create_wave` correctly refused fallback because no actions remained.

The run was interrupted after nine completed records (five conditional, four
single); the tenth arm was in progress and is excluded. No arm is rerun or
substituted. The [answer-free partial records](data/issue6-conditional-pilot-aborted-2026-11-18.json)
show zero fallback dispatches among the five conditional arms. They are
retained solely to audit the abort, not analyzed as a 12-cluster result or
used for a P5 gain claim. A recursive key and value audit found no candidate,
answer, digest, component, private path, or 64-hex value.

The corrected study reserves two mediated actions for fallback, uses a new
seed and task IDs, and adds a scheduler test that consumes two lead actions
before dispatching the second wave. It is separately preregistered in
`issue6-conditional-reserve-pilot-preregistration-2026-11-18.md`.
