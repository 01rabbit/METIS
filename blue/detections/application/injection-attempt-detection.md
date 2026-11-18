# Link suspicious input to an observed backend consequence

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Did untrusted input alter backend behavior, or was it only a rejected or harmless request?

## Evidence to request

Request identifiers, route and parsed parameter metadata; WAF/application validation outcomes; database, filesystem or process evidence; decoding rules applied by each layer.

## Reasoning procedure

- Preserve distinctions among raw bytes, URL-decoded values and framework-parsed inputs. Avoid repeatedly decoding until text looks suspicious.
- Classify the affected interpreter or operation: database, command execution, directory query or filesystem path. The evidence requirements differ by destination.
- Join a suspicious request to its actual backend action using a stable request/trace identity. A nearby exception from another request is not confirmation.
- Separate attempted input, validation failure, backend evaluation and unauthorized effect. An exception can accompany both a blocked attempt and an ordinary programming error.

## Alternatives and limits

Free-text editors, search fields, developer tools and encoded identifiers legitimately contain unusual punctuation. A web-tier pattern cannot confirm backend execution without an attributable consequence.

## Discriminating checks

Use inert request metadata containing ordinary punctuation, a blocked input, an unrelated backend error and a correctly correlated side effect. Do not send attack strings to a service. Response hardening or rule deployment is an approved external write.

## Concrete observation contract

Preserve the HTTP method, route, selected query/body location, content type and decoding
state. In IIS W3C data, `cs-uri-query` covers the URL query, not form or JSON bodies.
Use a trusted request/trace identifier to relate application parser errors and backend
activity; an address and timestamp do not uniquely identify a pooled request.

Record the backend's error class/code, affected operation and completion status rather
than treating an input marker as proof. A database `sql_state_code`, an application
validation rejection and a completed protected operation are different observations.
One normalization pass must follow the real application/parser contract, preserving raw
evidence; repeated decoding until text looks suspicious can create false matches. Include
rejected input with no backend effect and a normal complex request as negative fixtures.
