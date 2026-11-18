# Assess impaired script inspection

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Was script inspection disabled or altered, and did relevant execution continue under reduced protection?

## Evidence to request

Script logging and engine version, inspection/endpoint protection status, process/module events, approved acquired memory and administrative configuration records.

## Reasoning procedure

- Treat suspicious script text as intent or capability until a state change is observed. Quoted research material and blocked scripts can contain the same terms.
- Compare protection state before and after the suspected change. Missing events can arise from collection loss or unsupported logging, not only deliberate impairment.
- For memory evidence, verify module identity and version before assessing changed code. Generic byte patterns or a single return instruction cannot establish an unauthorized patch.
- Relate the impairment observation to subsequent behavior in the same process/session. Loading an inspection library does not show whether inspection was successfully invoked.

## Alternatives and limits

Security products, application compatibility tooling, engine differences and diagnostics alter visibility. Some script engines may not participate in the expected inspection path.

## Discriminating checks

Test ordinary inspection, a blocked suspicious script, service telemetry loss and an evidenced state change. Check that a missing module event is not labeled impairment. Restoring protection or terminating execution requires a scoped operational decision.

## Concrete observation contract

In Microsoft-Windows-PowerShell/Operational, event 4104 supplies script-block observations
when enabled; use `ScriptBlockId` and fragment numbering to reconstruct a block. Event
4103 module logging requires its own collection configuration. Strings indicating a
security-control change establish intent in the observed script, not that the change
succeeded or that every subsequent script was invisible.

Microsoft-Windows-Windows Defender/Operational 5007 reports configuration change; retain
the previous/new setting and correlate it with policy deployment or maintenance. Event
1116 concerns detection and 1117 action, with their own result details. These are not a
universal AMSI-bypass event. Compare enabled policy, actual collector health and subsequent
scan/detection coverage before claiming impairment. Missing telemetry may have several
causes; the card does not include a bypass payload or an active disabling test.
