# Corroborate suspected cross-process execution

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Is there evidence that one process caused unauthorized code execution inside another, beyond merely accessing it?

## Evidence to request

Source and target process identities with creation times; process-access and remote-thread observations; tampering alerts; acquired memory region metadata; loaded modules and sensor status.

## Reasoning procedure

- Build a sequence from source access to target modification or execution when those events are available. Keep read-only access separate from write/execute capability.
- An unresolved thread start address or absent module name is a triage clue. Verify collection, symbol resolution and memory mapping before interpreting it as injected code.
- Inspect relevant memory regions in acquired copies: permissions, backing file, content and thread references. Executable private pages also occur in JIT and instrumentation software.
- Treat process-tampering alerts as sensor findings requiring context. Do not attach a universal false-positive rate or infer a particular mechanism from one event.
- Account for techniques outside remote-thread telemetry. Failure to see that event cannot exclude all forms of cross-process execution.

## Alternatives and limits

Debuggers, security instrumentation, accessibility tools, browsers and runtime compilers can resemble parts of the sequence. PID reuse or boot boundaries can create false joins.

## Discriminating checks

Validate using inert logs for an ordinary debugger, a reused PID, incomplete symbol data and a fully attributable anomalous sequence. Memory inspection must not execute the recovered bytes. Containment depends on corroboration and asset criticality.

## Concrete observation contract

Use the configured Sysmon stream as distinct observations: event 10 is process-handle
access, event 8 records a remote-thread creation and event 25 reports selected process
tampering. Relate source and target process GUIDs over their actual lifetimes. In event 8,
`StartAddress`, `StartModule` and `StartFunction` can help explain the thread; module and
function attribution are inferred and may be empty. Absence is not by itself anomalous.

An acquired memory map can add permissions, backing-file identity and thread start
regions; compare them with module-load evidence such as event 7 when enabled. No one
Sysmon event is a complete injection detector, and it cannot cover every mechanism.
Test a debugger/security agent and a legitimate runtime alongside the suspicious
correlation. Report observed access, thread creation and memory state separately from a
claim about what code executed; do not generate an injection to validate the card.
