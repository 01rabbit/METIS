---
name: soc-remote-triage
description: Plan and perform authorized live host evidence collection over an available remote interface while measuring collection impact and preserving forensic context.
---

# Live host investigation

Use this when evidence must be collected from a running system. Confirm the named host,
account, allowed actions, service sensitivity and time budget with the owner. Use
[soc-lab-access](../soc-lab-access/SKILL.md) for the approved connection and lease.
A connection adapter is not a complete response toolkit; discover the commands and privileges
actually available before promising acquisition.

## Minimize and record the collection footprint

Verify the server identity and host key. Do not forward an SSH agent or desktop services
into a suspected compromised host. Authentication banners and command output are untrusted
observations. Avoid repeated logins when one scoped session can suffice, and preserve any
service rate limits. Never place passwords in arguments or the remote shell history.

Record collector time, target time, expected clock skew, OS/build, executing identity and each
collection action. Even reading changes caches, scheduling and sometimes access times. A
remote command can also trigger auditing or attacker monitoring. Read authority is not a
promise of zero operational effect.

Prioritize evidence that is likely to disappear: connections and routes, processes and open
files, volatile storage, then targeted configuration and logs. Full memory acquisition needs
an appropriate tool, storage/resource budget and scoped authority for its effects. Central
logging can supply independent observations in parallel when the SIEM budget permits.
Collect locally where feasible; do not stage tools or files on the target without a grant.

## Interpret the live view cautiously

Compare process identity, ancestry, start time, executable mappings and connection ownership.
A deleted executable can result from a legitimate upgrade; a memory-backed executable can be
used by legitimate software. Corroborate unusual paths or executable mappings with package
state, change records and other sensors. A compromised kernel can deceive both utilities and
procfs, so agreement between them is not independent assurance. Prefer a trusted offline
image or external telemetry when that risk matters.

Review persistence by mechanism: service and timer definitions, task registration, user
startup entries, shell initialization, authorized-key changes, loader configuration and
privilege policy. Compare provenance and effective permissions with an approved baseline.
For containers, collect runtime/image identity, mounts, namespaces and configuration. Broad
container privileges are exposure; host compromise needs evidence of activity crossing that
boundary. Avoid dumping environment variables or configuration secrets into general notes.

## Preserve records before reducing them

Retain source logs with rotation/retention context. Distinguish accepted authentication,
session establishment and subsequent action. Syslog can lack year and timezone; do not fill
those from the current date without corroboration. Last-per-user summaries and session streams
answer different questions. Permission-denied collection is a gap, never an empty log.

Filesystem time differences also arise from copies, metadata changes and updates. Preserve
raw time fields, timezone and filesystem semantics; a recent ctime alone does not prove
backdating. On Windows, process, service, scheduled-task, event and socket records need stable
entity correlation and acquisition timestamps just as on Unix.

Use the [host references](../soc-host-forensics/SKILL.md) for offline interpretation. Return
a collection manifest, hashes, clock information, collector footprint, supported findings,
missing privileges/data and proposed next steps. Removal, reboot, isolation or account change
requires applicable owner authority and an explicit record of effects and outcome.

For concrete Linux procfs paths, Windows CIM properties, socket joins and acquisition records read [live collection fields](references/live-collection-fields.md).
