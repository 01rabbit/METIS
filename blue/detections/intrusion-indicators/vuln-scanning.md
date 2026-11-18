# Identify assessment-like request patterns without assuming compromise

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Is a source performing systematic checks of application or service behavior, and is that activity authorized?

## Evidence to request

Request/flow metadata, WAF/IDS classifications, response outcomes, scanner inventory, source ownership and approved assessment windows.

## Reasoning procedure

- Consider breadth of checks, repeated response-dependent requests and protocol mismatch as a pattern; any one signature may match normal clients.
- Separate authorized scanners from unexplained sources using a current grant and identity, not a permanent IP-only exclusion.
- Retain request attempts and outcomes independently. A detector label naming a vulnerability does not establish that the target is vulnerable or that exploitation succeeded.
- Correlate meaningful backend effects before escalating from assessment activity to a compromise finding.
- Include denied and malformed requests while checking whether upstream controls prevented the request from reaching the service.

## Alternatives and limits

Health checks, compatibility probes, search crawlers and security validation can look similar. Source addresses may belong to shared services or approved vendors.

## Discriminating checks

Test authorized assessment, expired authorization, generic scanner-like user agents, blocked requests and an unrelated backend failure. The rule must not promote a signature name into a vulnerability verdict. Rate limiting or blocking requires service-owner authority.

## Concrete observation contract

Read the web collector's field header before counting requests. In IIS W3C data, bind
`c-ip`, `cs-method`, `cs-uri-stem` and `cs-uri-query` to `sc-status`, `sc-substatus`,
`sc-win32-status` and `time-taken` when selected. User-agent spelling follows the actual
header. The query column is not the request body. WAF rule ID, action and request ID are
vendor fields to map explicitly, not universal columns.

Group route breadth and error patterns by a justified client identity, with trusted proxy
handling, crawler/service inventory and duplicate removal. Repeated requests to different
routes can indicate enumeration without proving exploitation. A successful response code
needs application authorization and outcome evidence before it can establish access to a
protected object. Preserve rejected and missing-body requests as separate populations.
