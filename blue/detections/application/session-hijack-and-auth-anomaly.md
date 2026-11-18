# Investigate session use that does not fit its authentication history

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Does a session authorize requests that are inconsistent with its verified creation and subsequent security decisions?

## Evidence to request

Session creation/revocation and account binding; identity-provider events; reverse-proxy trust configuration; device context and server-side access decisions.

## Reasoning procedure

- Resolve the client address through the documented proxy chain. Untrusted forwarding headers cannot establish session origin.
- Compare pseudonymous session identity, account, authentication strength, device and network context across time. Choose windows from session lifetime and logging delays.
- Treat divergent geography, autonomous system or user agent as prioritization inputs. Roaming, VPNs and software updates can change them without theft.
- Look for access after revocation, impossible concurrent use supported by device evidence, or unauthorized sensitive actions. Mere absence of a visible login is not bypass when login history is incomplete.
- Count distinct sessions separately from accounts and requests; a many-to-many join can falsely inflate concurrency.

## Alternatives and limits

Shared devices, federated sessions, token refresh, reverse proxies and multi-device users complicate attribution. Clock skew and partial sign-in collection can reverse the apparent sequence.

## Discriminating checks

Test normal roaming, refreshed tokens, missing login telemetry, true post-revocation access and duplicate request delivery. Stronger findings require authoritative session state. Session invalidation or account disabling needs a scoped response grant.

## Concrete observation contract

Anchor a session to the authoritative server's session reference and immutable account
key, recording issuance/rotation/revocation and the accepted protected operation. A raw
cookie or IP address is not a safe report identifier. For Entra evidence, use tenant plus
`UserId`, `AppId`, `Id`, `ResultType` and device context; keep `SigninLogs` separate from
`AADNonInteractiveUserSignInLogs`. `UserPrincipalName` can change and a sign-in correlation
ID is not a universal application session ID.

Attribute a forwarded IP only when the trusted proxy chain and header rewriting are
known. NAT, mobile networks and session refresh can explain location/device changes.
DeviceDetail or authentication-step data may be absent, so preserve nulls rather than
asserting an unfamiliar device. An anomaly in geography requires corroboration from
actual session use and policy, not just a short distance/time calculation.
