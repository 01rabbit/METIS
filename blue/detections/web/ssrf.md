# Trace server-originated requests to their initiating context

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Did untrusted input cause a server to contact a destination outside the application intended access policy?

## Evidence to request

Input/request IDs, application fetch logs, DNS resolution and redirects where recorded, destination policy, process/proxy egress and response-use evidence.

## Reasoning procedure

- Distinguish a destination string in user input from a server-issued request. Correlate through a request/trace identifier or another reliable application link.
- Evaluate the resolved destination and redirect chain, not only the initial hostname. Keep requested, resolved and connected identities separate.
- Compare internal or metadata-service access with legitimate workload behavior. Such addresses can be normal dependencies and do not alone prove abuse.
- Separate connection attempts, successful responses and any sensitive response delivered onward. A denied egress attempt is not completed data retrieval.
- Document paths bypassing the visible proxy or missing process attribution before ruling out activity.

## Alternatives and limits

Webhook processors, preview services, health checks, cloud SDKs and integration jobs intentionally fetch resources. Shared egress can make unrelated requests appear correlated.

## Discriminating checks

Test an approved fetch, a user-supplied URL never fetched, a blocked request, a redirect and an attributable unauthorized destination. Use synthetic logs only. Do not request internal endpoints to reproduce the behavior.

## Concrete observation contract

Bind an incoming request to its outgoing HTTP client span. In OpenTelemetry conventions,
`server.address`/`server.port` represent the logical destination, while
`network.peer.address` may name a proxy or connection peer. `url.full` can describe the
original URL before redirects. It is not proof that the final server was contacted.
Retain DNS answers, redirect steps and trusted proxy records when they are needed to
establish the actual egress target; remove embedded credentials and signed parameters.

An input URL, failed lookup and successful remote response are separate observations.
Confirm the returned status and application use of the result, then relate any protected
data effect. Health checks, preview services and approved cloud SDK activity are benign
comparisons. The absence of client spans limits causal attribution even if network
traffic exists. No metadata-service address or active probing recipe is needed for this card.
