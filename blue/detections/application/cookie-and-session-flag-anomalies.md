# Assess session-cookie configuration and session continuity

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Is a session protected as intended, and does its lifecycle show a security-relevant deviation?

## Evidence to request

Sanitized response-cookie attributes; session issuance, renewal, login and logout records; server-side account/session bindings; request transport and application policy.

## Reasoning procedure

- Evaluate Secure, HttpOnly and SameSite attributes against cookie purpose and the application threat model. Parse attributes structurally and account for multiple Set-Cookie fields.
- Keep the controls distinct: Secure constrains cookie transport, HttpOnly prevents ordinary script access to the cookie, and SameSite influences cross-site attachment. HttpOnly does not stop the browser sending the cookie on a request; SameSite is defense in depth against CSRF, not a substitute for application authorization or CSRF checks. Site and origin are different boundaries.
- Compare pre-authentication and post-authentication session state. A stable identifier is a configuration concern only after accounting for framework-specific renewal and server-side invalidation.
- Investigate subsequent access using a revoked or unexpectedly shared session with server-side authorization evidence. IP or user-agent changes alone do not establish theft.
- Use keyed pseudonymous session references in analyst tables. Raw cookie values are credentials and should not enter the knowledge repository or reports.

## Alternatives and limits

Federated login, embedded applications, mobile roaming and device upgrades produce legitimate session changes. An access log ordinarily lacks response-cookie attributes and cannot validate issuance flags.

## Discriminating checks

Test duplicate cookie names with different paths, case-insensitive attributes, a normal authentication rotation and benign network changes. A posture defect must not automatically become an account-compromise finding. Changing cookie behavior requires application-owner approval.

Control semantics: [session management reference](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

## Concrete observation contract

Inspect the response's `Set-Cookie` metadata, not only the next request's `Cookie` header.
Retain cookie name, Domain and Path together with the browser/profile and partition
context; matching those three attributes alone does not identify a partitioned cookie.
Record `Secure`, `HttpOnly` and `SameSite` independently. Secure
restricts transport, HttpOnly restricts script access, and SameSite controls cross-site
sending behavior; none substitutes for server-side authorization. Modern browser handling
of `SameSite=None` requires Secure, subject to the browser/version being assessed.

For CHIPS, preserve the `Partitioned` attribute and the acquired partition key. The
key includes the schemeful top-level site, so equivalent name/domain/path tuples in
different partitions must remain separate. With compatible acquired Chrome DevTools
Protocol metadata, `Network.Cookie.partitionKey` is an optional experimental object:
`topLevelSite` is a string and `hasCrossSiteAncestor` is a Boolean. The separate optional
`partitionKeyOpaque` Boolean identifies an opaque key; do not replace it with an invented
site. Preserve the full reported key and browser/protocol version. Unsupported or
incomplete collection can omit this metadata, leaving the partition unresolved. A request
`Cookie` header alone does not recover the cookie storage context. These checks use
retained metadata and require no cookie replay or new requests.
[CHIPS partitioning](https://privacysandbox.google.com/cookies/chips) and
[version-dependent CDP schema](https://github.com/ChromeDevTools/devtools-protocol/blob/master/json/browser_protocol.json).

Join issuance, rotation, logout/revocation and observed acceptance using a private,
consistent session reference without copying raw cookie secrets into reports. The
presence of a missing flag is a configuration finding; session compromise requires
evidence of an unauthorized accepted action. Scope/path changes, multiple application
cookies and staged deployments are necessary benign comparisons.
