# Investigate repeated authentication challenges and later identity use

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Does a sequence of authentication challenges followed by access represent ordinary user friction or unauthorized use?

## Evidence to request

Interactive and noninteractive sign-ins, detailed authentication steps, account/device and application identity, conditional-access outcomes, session/token references and directory audit events.

## Reasoning procedure

- Separate explicit challenge rejection from timeout, cancellation and generic failure. A summary error code can combine different user outcomes.
- Group by stable identity and relevant application/device context; avoid merging challenges across unrelated sessions or devices.
- Follow a later success into observed resource access, token use and directory changes. A success event alone does not establish which human approved it.
- Review noninteractive activity separately; it can continue an existing session without a new interactive prompt.
- Confirm log types, retention, tenant coverage and licensing. A clean interactive feed cannot exclude service-principal or token-related activity.

## Alternatives and limits

Poor connectivity, device enrollment, expired sessions and legitimate travel create repeated prompts. Network location may reflect a proxy rather than the user.

## Discriminating checks

Test timeout-only sequences, user-denied challenges, an unrelated success and subsequent privileged activity with a valid identity link. Record exactly which authentication detail supports the finding. Revocation or policy changes require the identity owner.

## Concrete observation contract

For Entra `SigninLogs`, retain `Id`, tenant context, `UserId`, `AppId`, `IPAddress`,
`ResultType`, `ConditionalAccessStatus`, `DeviceDetail`, `AuthenticationDetails`,
`CorrelationId`, `CreatedDateTime` and `TimeGenerated` where available. Interpret the
serialized authentication steps against the current table schema. String result `0`
means sign-in success; null is unknown. A failure code must be interpreted from its
documented reason rather than universally labeled a user-denied MFA prompt.

Keep `AADNonInteractiveUserSignInLogs` separate and state its aggregation/retention
behavior. Request rows do not equal individual prompts, and a client-supplied
`CorrelationId` is not a universal trusted session ID. Relate a successful sign-in to
subsequent cloud audit/resource activity through actual account/application/session
evidence. A travel or device anomaly without that binding remains a lead, not a
confirmed identity takeover.
