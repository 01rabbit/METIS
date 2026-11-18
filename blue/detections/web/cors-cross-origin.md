# Assess cross-origin access policy and observed disclosure

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Does an application permit an untrusted origin to read a protected response in a browser context?

## Evidence to request

Request origin, response CORS fields, credential mode where known, route authorization, actual response classification and browser/application observations.

## Reasoning procedure

- Distinguish policy posture from an observed cross-origin read. A permissive header by itself does not prove sensitive content was exposed.
- Evaluate the combination of origin handling, credential use, preflight requirements and browser enforcement for the particular request.
- A wildcard Access-Control-Allow-Origin does not grant a credentialed browser response read, even alongside Access-Control-Allow-Credentials. Check the actual origin match and browser outcome. A response being unreadable does not mean a non-preflighted request never reached the server; CORS is not a general CSRF control.
- Check cache variation and origin reflection with retained evidence; a response associated with one request must not be attributed to another origin.
- Relate any claimed data disclosure to the protected resource and requesting identity. Server-to-server requests are not governed by browser CORS in the same way.

## Alternatives and limits

Public APIs, intentional integrations and noncredentialed resources may use broad origins legitimately. An ordinary access log often lacks response headers and browser read outcome.

## Discriminating checks

Test public data, a denied browser read, an approved integration and a retained protected response with incorrect origin authorization. Do not probe a live application with new requests. Policy changes need application-owner review.

Browser enforcement details: [CORS reference](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS).

## Concrete observation contract

Pair the actual request's `Origin` with that response's `Access-Control-Allow-Origin`
and `Access-Control-Allow-Credentials`, preserving scheme, host and port. A reflected
origin is only a header observation until the browser's credential mode and response
contents are known. The wildcard origin does not authorize a credentialed browser read.
`Vary: Origin` matters when caches serve different origin-dependent responses.

Relate any OPTIONS preflight to the later actual request and account context; a
permissive preflight alone proves neither that the actual request succeeded nor that
protected content was readable. Distinguish a public unauthenticated response, a
credentialed read permitted by policy and an unauthorized disclosure. A state-changing
request may have a CSRF issue without a CORS read issue, so do not infer one from the
other. These checks use retained browser/server evidence, not a test against a live victim.
