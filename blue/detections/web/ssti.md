# Assess template processing with evidence of evaluation

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Has untrusted content changed template evaluation, rather than being displayed or rejected as ordinary text?

## Evidence to request

Template engine/version, route and input provenance, render/error records, retained output classification, application trace and process/network effects.

## Reasoning procedure

- Identify whether the input reaches a template source or only a data value. Unusual delimiters are not a substitute for tracing the rendering boundary.
- Separate rejected input, parse errors, evaluated output and unauthorized effects. A template error may be a deployment defect.
- Correlate output or side effects to the same render operation; a nearby application error cannot confirm evaluation.
- Account for cached and asynchronous rendering, where request time and render time can differ substantially.
- Escalate based on evidenced access or execution, not on an engine name or an input pattern alone.

## Alternatives and limits

User-authored templates, documentation, localization and ordinary formatting errors can resemble suspicious content. Standard access logs rarely observe template evaluation.

## Discriminating checks

Test literal text rendering, a parse failure, an approved user template and an attributable policy-violating render outcome. Do not construct or submit evaluation payloads. Remediation is a reviewed application change.

## Concrete observation contract

Ask for the renderer name/version, effective template configuration, template identifier
or digest and request/trace ID. A renderer-specific syntax exception locates parsing;
it does not show that an expression executed or that user input became template source.
Application route and response status are insufficient to establish that boundary.

Relate the actual rendered response to its template version and authenticated context,
then assess any file, process or network effect through the same operation. Define
custom trace fields explicitly rather than inventing a universal template audit table.
Normal dynamic text, an escaped value and a rejected template must differ from a
confirmed unauthorized evaluation in the fixtures. Inspect retained inputs as data;
do not submit evaluation payloads or invoke an untrusted template engine during review.
