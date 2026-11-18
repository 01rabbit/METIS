# Follow unsafe markup from input to browser impact

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Was active content merely submitted, safely rendered as text, stored for later use, or actually executed in a victim context?

## Evidence to request

Request and content-record identifiers; sanitizer/template decisions; retained response context; CSP reports where available; browser or application impact evidence.

## Reasoning procedure

- Separate reflected, stored and client-side processing paths. A server request log may never contain a client-side source or sink.
- Determine the rendering context and the encoding/sanitization actually applied. Suspicious text in a request is not proof that the response was executable.
- For stored content, link creation, later retrieval and affected viewers through stable content IDs. The submitter and the potentially affected user can differ.
- Use CSP violations as observations of a policy decision, then inspect whether the operation was blocked. A violation report is not automatic execution evidence.
- Bound account or data impact to observed actions; never infer credential theft from markup alone.

## Alternatives and limits

Code snippets, WYSIWYG editors, training content and security testing may contain active-looking text. Extensions and browser instrumentation can also generate CSP noise.

## Discriminating checks

Use inert records for encoded text, sanitized storage, a blocked policy event and attributable browser execution metadata. Do not render unknown markup in an authenticated browser. Content removal or account/session actions require scoped authorization.

## Concrete observation contract

For browser CSP evidence, distinguish the older report shape (`blocked-uri`,
`effective-directive`, `script-sample`) from Reporting API fields such as `blockedURL`,
`effectiveDirective` and `sample`. Preserve `disposition`: report-only observations do
not mean the browser blocked execution. Samples may be absent or intentionally limited,
and reports themselves are untrusted input to the collector.

For stored content, join the application write's content/object ID to the later rendered
view and browser context. A matching URL alone cannot show which stored version a victim
received. For reflected content, require the actual response/rendering context and its
encoding. A CSP event, source marker or HTTP success is not proof of credential theft or
script execution. Ordinary template changes and browser extensions are alternatives;
acquired markup must be inspected without rendering active content.
