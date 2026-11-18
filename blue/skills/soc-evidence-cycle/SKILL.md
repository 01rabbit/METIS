---
name: soc-evidence-cycle
description: Operate repeatable defensive evidence intake, artifact-specific analysis, independent verification and reusable lesson capture.
---

# Evidence analysis cycle

Start with tool availability, evidence inventory, scope and resource preflight. Snapshot input
identity, byte count, SHA-256, collection time and parser version. Work from immutable originals
and keep transformations in the private case workspace.

Distinguish acquisition failure, parse failure, incomplete coverage, tool unavailability and a
negative finding. Each requires a different next step. Assign disjoint artifact work to bounded
workers and use an independent evidence check for high-impact conclusions. Return the supporting
fields, not merely a confidence label. A high confidence score does not repair missing provenance.

For binary analysis, instruction boundaries need a supported decoder, exact architecture and
version, immutable byte hashes and contiguous coverage. A byte-pattern match or caller-supplied
address is not a validated instruction. A receipt establishes only the region actually decoded;
it does not prove exhaustive binary-wide control flow. Report unsupported decoding honestly.

Preserve chain of custody across host snapshots, packet captures, cloud events, memory images,
mail, browser databases, documents and archives. Identify missing extraction layers before
claiming absence. Use focused parser tests and retained benign fixtures. Do not run malware or
perform vulnerability reproduction as part of this cycle.

At completion, reconcile task states and resource leases, collect transcripts and usage, and
write a generic lesson stripped of case identities and secrets. Promotion into a tracked skill
requires review; raw evidence, full findings, communications and token logs remain private.

Keep source location, acquired copy and per-record location distinct using [evidence locators](../soc-triage/references/evidence-locators.md). For container metadata, typed IDs or exact numerical selection, use [concrete container and structured fields](../soc-triage/references/container-and-structured-fields.md).
