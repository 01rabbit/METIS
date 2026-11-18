# Investigate unexpected shared-object state in JavaScript workloads

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Has untrusted data changed object behavior beyond its intended record or request?

## Evidence to request

Parsed input provenance, merge/configuration code path identification, application diagnostics, object-state observations, request/worker identity and downstream effects.

## Reasoning procedure

- Inspect whether suspicious keys reached a relevant merge or assignment boundary; their appearance in a request is only an attempted input.
- Separate per-object data changes from inherited/shared state changes. The impact depends on how later code reads the affected property.
- Follow state lifetime across subsequent requests in the same worker. The causing request and the affected request can be different.
- Correlate downstream authorization, rendering or process effects only when the changed state is evidenced; a crash alone does not establish the mechanism.
- Review restarts, cache resets and worker routing when interpreting the absence of later effects.

## Alternatives and limits

Legitimate metadata, configuration imports and framework internals can contain similarly named fields. Logging may show keys while omitting how the application used them.

## Discriminating checks

Test harmless stored keys, rejected input, a worker restart and evidenced state affecting another request. Use synthetic state descriptions, not pollution payloads. Code/configuration repair is a separately reviewed change.

## Concrete observation contract

Record the application/runtime version, worker identity and request/trace ID around the
relevant parse/merge operation. Any proposed fields describing parsed key types,
merge-policy decisions or property ownership are custom instrumentation and must be
verified with the owner. A suspicious key in a request does not show that an inherited
property changed or was used.

For a persistent worker, relate the state observation and later behavior to that same
worker lifetime; a restart or different worker breaks the relation. Distinguish an own
property from one obtained through the prototype chain in retained diagnostic evidence.
An unrelated request may observe changed shared state, but causality needs the earlier
operation and intervening activity. Rejecting a key, a harmless merge and a confirmed
unauthorized outcome require separate fixture results; no pollution payload is included.
