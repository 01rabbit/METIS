# Detection validation integrity

A rule is a candidate until its actual branch, query dialect and sensor path have evidence.
Use existing benign/incident logs or inert synthetic records. Do not validate by executing
malware, reproducing a vulnerability or constructing an exploit.

Record rule digest, backend/version, field normalization, time window, input digest and
complete output. Distinguish three claims: fixture matches a predicate; parser/query executes;
actual sensor emits the needed fields. None implies the others.

Check every branch and boundary independently. Include a positive inert record, a near-miss,
benign baseline, missing-field case, ordering change, stale event, alternate entity and
window boundary. Record actual observations; fixture parameters are not target telemetry.
An emitter that omits a required field cannot validate that branch. A permissive parser stub
or a successful syntax check does not validate backend semantics.

Measure false positives over the intended population with explicit denominators. Preserve
false negatives, partial results and unsupported branches. A result from another environment,
machine, sensor or rule revision does not validate the current one.

Correlate by the actual entity key and observed source address, not an asserted address inside
a message. For DNS use a documented Public Suffix List version and decide whether private
suffixes apply; simplistic last-two-label grouping can combine unrelated tenants. NAT,
proxies, recycled PIDs, time skew and duplicate collectors can invalidate an otherwise correct
sequence.

For Windows read-only verification, select known provider/EventID/host/time records from an
existing event log and compare raw fields to normalized SIEM output. Account for collection
delay and missing audit configuration. A missing event must be reported as a telemetry gap.

Deployment needs user or scoped owner authority, saved rollback state and a named operator.
Keep validation evidence in private case storage. Promote only a generic rule, field contract,
documented limitations and verified status; never copy an incident's secrets or answer catalog.

## Concrete observation contract

The mapping worksheet must retain raw provider/channel/table, event or action version,
field name, data type, encoding, normalized name and missing-value rule. Attach a retained
example locator and the collection settings that make each required field available.
For Windows keep provider, channel, event version and record ID separately. For auditd,
verify the multipart event was reconstructed before asserting an argv/path relation.
For database audit, distinguish an allowed permission from completed execution.

Assign inert fixture records stable IDs and hashes. Record the expected matching IDs,
entity joins, time-order/window result and decision, then compare the actual output's
membership rather than only its total. Include another host with the same local ID,
truncated arguments, stale policy, unknown result and a missing required correlation key.
Record pagination, caps, partial counts and backend errors as test outcomes.

Use the [Windows](telemetry-windows.md), [Linux/network](telemetry-linux-network.md),
[application/identity](telemetry-application-identity.md) and
[specialist](telemetry-specialist.md) contracts for source-specific checks. They are
documentation, not sensor emitters. A changed rule, mapping or knowledge digest must not
inherit an older fixture or model score as if the exact revised content had been tested.
