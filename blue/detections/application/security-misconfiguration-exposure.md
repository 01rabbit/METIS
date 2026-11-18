# Distinguish endpoint discovery from actual exposure

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Did a requester reach restricted information or capability, and what authorization should have prevented it?

## Evidence to request

Route inventory, expected authorization policy, request/response metadata, retained response classification, identity context and application audit outcomes.

## Reasoning procedure

- Compare requested resources with the maintained inventory of administration, diagnostics and configuration surfaces. Endpoint names alone become stale as applications change.
- Measure distinct resources per source and interval when looking for exploration; retain failed attempts and account for reverse proxies, scanners and shared egress.
- A successful HTTP status may contain a login page or a generic response. Confirm that protected content or a protected operation was actually available.
- For unusual methods, inspect the application action and authorization decision. Method acceptance alone does not prove a sensitive modification.
- Report a discovered weakness independently from evidence that someone used it. Prioritize by reachable capability and data sensitivity.

## Alternatives and limits

Asset scanners, health checks, support diagnostics, SPA fallback routes and application redirects are common alternatives. If response content was not collected, state exactly which exposure claims remain unverified.

## Discriminating checks

Test a nonexistent path returning 200, an authorized diagnostic request, a denied request and an unauthorized retained response. Avoid probing production endpoints to fill a telemetry gap. Fixes belong to the application owner.

## Concrete observation contract

Use the approved route/configuration inventory to identify diagnostic, administrative or
build-output exposure; do not discover it by trying a list of sensitive endpoints. Bind
IIS `cs-method`, `cs-uri-stem`, `sc-status` and `sc-bytes` or equivalent fields to the
application's authorization decision and resource classification. Response length does
not reveal the content, and a 200 response can be a generic page or login shell.

Record the effective virtual host, route, application version and the principal presented
to the decision. Require retained content metadata or a service-owner-confirmed result
before concluding that a private resource was returned. A publicly intended health page
and a protected diagnostic output should be separate fixtures. Missing body visibility
limits the conclusion to exposure potential, not confirmed data disclosure.
