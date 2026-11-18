---
name: ctf-pwn-solve
description: Analyze memory-safety artifacts, crash evidence and platform mitigations for defensive triage, without constructing or delivering exploits.
---

# Memory-safety evidence analysis

This skill retains the memory-safety subject area as defensive investigation. Use supplied
binaries, crash dumps, build information and telemetry as evidence. Do not construct payloads,
reproduce a vulnerability, develop a bypass or execute an intrusion workflow.

Inventory the file hash, architecture, build, loader, library and kernel versions. Record
PIE/ASLR, NX, stack protection, RELRO, CFI/CET and allocator hardening as observed properties;
none individually proves the program safe. Classify the suspected bug as bounds violation,
use after free, type confusion, format-string misuse, arithmetic error or lifetime error.
Distinguish an observed crash from a theoretical failure and from confirmed exploitation.

Environment fidelity matters: emulator, CPU features, kernel, ABI, mitigations, library,
randomness and concurrency can change behavior. A successful synthetic test does not establish
production behavior. Record which assumptions were measured and which were merely held fixed.
A native rerun can exclude an emulator artifact but cannot validate a flawed experiment.

For investigation, correlate crash time, faulting module, process ancestry, allocation history,
service restarts, authentication, child processes, credential changes and file/network activity.
Kernel incidents need kernel logs, boot integrity and privilege transition evidence. Missing
telemetry is a collection gap, not evidence of absence. Availability impact is a valid finding.

Recommend supported fixes, dependency updates, isolation and additional telemetry. Validate
remediation with normal-input regression tests and existing crash records; use no exploit code.
Write a detection with the observed preconditions, false-positive cases and coverage limits.

Read [the concrete evidence reference](references/crash-evidence.md) for dump/journal fields, process lifetime joins, mitigation metadata and impact limits.
It adds observation coordinates and validation criteria; no exploit, live oracle or sample execution is provided.
