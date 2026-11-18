# Investigate unexpected execution associated with a document application

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Did opening or processing a document cause unexpected system activity, and can the responsible document be identified?

## Evidence to request

Document hash/path and acquisition context, application/process history, child or brokered execution, macro/security decisions, file writes and subsequent connections.

## Reasoning procedure

- Separate a document being present, opened, permitted to run active content and causing execution. These are different observations.
- Correlate the application process to the document and downstream activity. A child of a document application can come from an add-in or user action.
- Include brokered actions when the immediate parent is a service rather than the document application; require a reliable linkage rather than host-wide proximity.
- Consider archives, remote templates and embedded objects as acquisition context without fetching their referenced resources.
- Assess resulting privileges, persistence and data access only from observed downstream evidence.

## Alternatives and limits

Add-ins, accessibility software, document conversion and enterprise automation often launch helpers. Protected-view and policy blocks can stop a suspicious document before execution.

## Discriminating checks

Test an approved add-in, a blocked active document, a file merely downloaded and an attributable unexpected child. Work only on acquired copies and inert records; do not open unknown active documents to make the alert fire.

## Concrete observation contract

Start with the Office process's Sysmon 1 GUID and follow actual child/descendant GUIDs.
Keep the document's acquired path/hash and any Sysmon 11/15 creation/stream provenance
separate from the process image. A document open alone does not prove macro execution.
For Security 4688, command-line availability depends on policy; missing text is a coverage
gap. For PowerShell 4104, assemble the `ScriptBlockId` fragments before interpretation.

Defender events 1121/1122 in Microsoft-Windows-Windows Defender/Operational distinguish
ASR block from audit behavior. Preserve rule identity and mode; an audit event does not
show that a block failed. Brokered execution can break an immediate Office-parent match,
so require a supported cross-process relation rather than inventing ancestry. Approved
add-ins, document-conversion helpers and a blocked attempt need distinct fixture outcomes.
