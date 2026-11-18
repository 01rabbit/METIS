# Investigate unexpected external resolution during XML processing

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Did processing an XML document cause an unauthorized external read or network request?

## Evidence to request

Parser configuration/version, document provenance/hash, parser diagnostics, application trace, external resolver activity and evidence of returned data.

## Reasoning procedure

- Distinguish declarations in input from parser resolution. A document may contain unsupported or disabled constructs without triggering external access.
- Tie a resolver or file operation to the relevant parse operation. Shared application processes may perform unrelated network requests.
- Determine whether external resources were permitted by application policy and whether any sensitive content reached a response or another destination.
- Keep failed resolution, completed retrieval and disclosure separate. A parser exception does not establish the last two.
- Check visibility for both filesystem and network resolution paths. An egress-only sensor cannot exclude local reads.

## Alternatives and limits

Approved schema retrieval, document validation and legacy integrations may use external resources. Sanitizers and secure parser settings can prevent resolution despite suspicious document structure.

## Discriminating checks

Test a declaration ignored by configuration, approved schema access, failed resolution and a trace-linked unauthorized read. Analyze acquired metadata rather than processing an unknown document with external resolution enabled.

## Concrete observation contract

Identify the parser and its effective version/configuration, not just a request's
`Content-Type`. XML may be nested in an uploaded package or another application format.
Bind the request/trace ID to parser diagnostics and external-resource resolution policy.
A declaration in input or a parser error establishes neither a file read nor a network
fetch.

For a claimed local file effect, correlate the application's process lifetime with audit
operation, PATH and success/exit evidence; this shows an operation, not automatically
which content was returned. For network resolution, relate host DNS and connection
records to the parser operation and observed destination. Legitimate schema/resource
loading is a counterexample. Missing body/parser instrumentation leaves the result
inconclusive; do not enable external resolution or submit a crafted document to validate it.
