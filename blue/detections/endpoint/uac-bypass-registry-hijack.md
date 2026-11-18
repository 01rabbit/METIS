# Correlate per-user launch configuration with elevated execution

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Did a user-controlled configuration influence a privileged launch outside the approved elevation workflow?

## Evidence to request

Registry before/after state and actor, relevant process ancestry, token/integrity context, operating-system build, elevation policy and administrative activity.

## Reasoning procedure

- Review changes to user-controlled launch associations in relation to subsequent privileged process creation. The changed value alone indicates configuration, not successful elevation.
- Validate that the affected launch behavior exists on the deployed build and policy. Historical technique names do not establish current applicability.
- Compare actual child identity and integrity with the initiating context. An executable name associated with elevation is not a token transition.
- Retain direct process observations when registry telemetry is missing, but mark the presumed configuration link unproven.
- Investigate cleanup of a relevant value as an event in its own right without treating absence of the value later as evidence it was never set.

## Alternatives and limits

User file associations, installers and administrative troubleshooting can create similar configuration changes. Legitimate consent-based elevation can produce the same privileged executable.

## Discriminating checks

Test ordinary association changes, approved elevation, configuration with no launch and an evidenced unexpected transition. Use recorded or synthetic telemetry only. Do not reproduce elevation behavior; reverting settings or ending processes requires a grant.

## Concrete observation contract

In Sysmon 12/13, retain the writing `ProcessGuid`, `Image`, `TargetObject` and written
`Details` where present. User class-registration state under `HKCU\Software\Classes`
must be resolved to the applicable user/SID, including its corresponding HKU path in raw
telemetry. Security 4657 is another registry-value modification source only when its
auditing prerequisites are met. Do not treat every user-class change as privilege abuse.

Require a later process with independently observed token/integrity context and bind it
to the changed state and originating user. `IntegrityLevel` or the provider's token
elevation field describes that process, not a privilege inferred from its executable
name. Preserve configuration-change, execution and elevated-effect findings separately.
The card intentionally excludes a registry-gadget/launcher recipe; installer association
changes and an unexecuted mutation remain important benign or incomplete cases.
