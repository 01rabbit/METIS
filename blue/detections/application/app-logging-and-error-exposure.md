# Separate application failures, information exposure and logging gaps

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Has an error disclosed sensitive implementation detail, or has a collection failure hidden security-relevant activity?

## Evidence to request

Application exceptions, HTTP status and request IDs, response inspection where explicitly retained, ingress counts, security-audit events and collector health.

## Reasoning procedure

- A server exception proves a backend failure; it does not prove the exception reached a client. Confirm exposure through retained response data or an application rendering record.
- Compare error rates within a stable endpoint and deployment version. Changes in response size are prioritization signals, not proof of leaked stack traces.
- For missing audits, define which ingress events should produce which security events. Allow known sampling, asynchronous delay and non-audited routes before identifying a gap.
- Keep collection loss distinct from application logging being disabled. Both reduce confidence in other detections but have different remediation owners.

## Alternatives and limits

Deployments, dependency outages, health checks and intentionally rejected requests cause error bursts. Redaction middleware may prevent disclosure even when detailed exceptions exist internally.

## Discriminating checks

Test a backend exception with a generic response, an actual retained sensitive response, delayed audit delivery and a collector outage. The output must distinguish exposure, service failure and unknown visibility. Enabling body capture requires privacy and retention review.

## Concrete observation contract

Locate the configured application error sink and access logs separately. IIS W3C fields
such as `cs-uri-stem`, `sc-status`, `sc-substatus`, `sc-win32-status` and `time-taken`
can locate a request but do not include the returned error body. A column purporting to
hold response content is custom instrumentation whose collection and redaction must be
verified. Read the actual `#Fields` header and site identifier before parsing.

Bind a server error to its request/trace ID, then compare with a retained response or
application disclosure record. An internal exception does not prove that the client saw
its details. Report the request denominator and log coverage per route/version; an empty
error search with a missing collector is unknown. Benign development diagnostics and a
generic error page require different outcomes from externally returned private details.
