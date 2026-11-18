# Correlate message delivery, interaction and account effects

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Did a suspicious message reach a person, and what evidence supports interaction or account compromise?

## Evidence to request

Mail trace and message identifiers, trusted authentication results, recipient and delivery disposition, attachment hashes, sanitized click records, browser/proxy and identity-provider events.

## Reasoning procedure

- Keep submission, acceptance, mailbox delivery, quarantine and user access separate. Retries and distribution expansion can create several records for one message.
- Evaluate sender identity, authentication alignment and business context together. Authentication success does not establish benign intent; failure can result from forwarding or configuration.
- Distinguish automated security-link fetching from a human click using the product event semantics and device context.
- Follow a click to the observed destination and subsequent authentication event without fetching the link. A landing page visit is not proof of submitted credentials.
- Separate attachment presence, download, opening and execution. Relate account effects only where session or device evidence supports the connection.

## Alternatives and limits

Marketing platforms, delegated senders, forwarded mail and security scanners create many apparent anomalies. Privacy redaction or product licensing can limit click/attachment telemetry.

## Discriminating checks

Test quarantined delivery, forwarded authentication failure, scanner-only clicks and a user interaction with corroborated sign-in activity. Use inert message metadata. Mail removal, domain blocking and session revocation require an applicable response grant.

## Concrete observation contract

In Defender mail telemetry, start with `EmailEvents.NetworkMessageId` and recipient
context. Preserve `SenderFromDomain`, `SenderMailFromDomain`, `DeliveryAction`,
`DeliveryLocation` and `AuthenticationDetails`. Authentication results require a trusted
provider trace/ingress boundary, not merely a header named Authentication-Results.
Do not assume a separate table with an invented authentication-table name exists.

`UrlClickEvents` can supply `NetworkMessageId`, `AccountUpn`, `Url`, `ActionType` and
`IsClickedThrough`. Relate the intended recipient, event time and observed account;
message-to-recipient-to-click joins are one-to-many and can multiply records. A delivery,
link preview or security scanner fetch does not prove a person's click or credential
entry. A subsequent accepted sign-in or endpoint event needs its own identity binding.
Record safe-link rewriting and absent mail licensing/retention as visibility limitations.
