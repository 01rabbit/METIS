# Assess proxy use and conflicting network identities

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Do network observations show a policy-relevant mismatch between the advertised connection name and the application destination?

## Evidence to request

Connection identifiers, TLS handshake metadata where visible, decoded application authority from an approved proxy, proxy policy decisions, endpoint process and proxy-configuration records.

## Reasoning procedure

- Compare handshake name and application authority only when they belong to the same attributable connection or request. Time proximity and a shared CDN address are insufficient joins.
- Document whether the application authority was actually visible. Encrypted traffic and encrypted ClientHello can limit what the sensor knows; an absent field may reflect collection behavior.
- Use repeated connections, rare destinations, unusual owning processes and configuration changes to prioritize review; none independently proves a covert channel.
- Validate differences against routing architecture, permitted forward proxies and service aliases. A mismatch is a finding about observed identities before it is an evasion conclusion.

## Alternatives and limits

CDNs, enterprise inspection, alternate authorities, connection reuse and split visibility create benign mismatches. Fingerprints are shared across software and change with versions; do not attribute an actor from a fingerprint.

## Discriminating checks

Test correctly joined mismatches, two unrelated simultaneous flows, missing handshake fields and known proxy transformations. Verify that absence and mismatch have different outputs. Blocking shared infrastructure requires a business-impact review.

## Concrete observation contract

With Zeek, `ssl.log` supplies `server_name` and connection `uid` when visible; relate a
HTTP request's `host` and `trans_depth` to that same connection. A proxy HTTP authority
and a TLS name taken from different sessions cannot establish a mismatch. Retain the
observed destination tuple and DNS resolution separately from the requested name.

Without decrypted HTTP or a trusted proxy record, the HTTP authority may be unavailable.
TLS 1.3 prevents ordinary passive extraction of server certificates, and ECH can obscure
the useful SNI. Mark the comparison unavailable instead of filling either side from a
later lookup. CDN aliases, shared hosting and approved gateways can explain apparent
differences; policy context and observed traffic destination are needed before escalation.
