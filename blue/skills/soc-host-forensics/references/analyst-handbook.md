# Connecting host evidence to conclusions

This guide selects and correlates evidence. It assumes read-only access to acquired artifacts
and format-appropriate tools. It does not provide image acquisition, a registry engine or a
binary event parser. Use [parser integrity](parser-integrity.md) for parser preflight and
[platform references](../SKILL.md) for individual formats.

## Establish an analysis set

Retain received hashes, collection method/time, host identity and all container segments.
Verify native container integrity when supported, then compare the extracted inventory with
the expected tree. A successful extraction can still omit unsupported items. Keep originals
and working output separate; a retry must be tied to the same input identity.

Create a source coverage table: host, artifact kind, retained interval, timezone/clock,
acquisition completeness and parser limits. Hostname reuse, restored images and copied logs
can mix machines or periods. Do not merge them merely because filenames match.

## Choose artifacts for the claim

| Claim | Useful corroboration | Interpretation boundary |
| --- | --- | --- |
| A program ran | Process-creation telemetry, supported execution traces, memory process records | Inventory, compatibility caches and strings can indicate presence without execution |
| A mechanism persists | Service/task/startup definition, related binary or script, registration audit, execution trace | Configuration is different from successful later execution |
| A user obtained a session | Authentication result, logon/session identity, session lifecycle and subsequent activity | A successful authentication can end before an interactive session exists |
| A file was accessed or transferred | Filesystem/change journal, application records, full path, access/network evidence | Recent-item shortcuts and timestamps can reflect metadata handling |
| A privileged change occurred | Effective policy/configuration before and after, initiating identity, audit | A writable object or permissive policy describes exposure, not observed abuse |

Select a narrow anchor event for the first timeline view and widen based on evidence.
Keep the unfiltered output and selectors so omissions are reversible. An all-events merge
can duplicate a fact across parsers; duplicated representation is not independent proof.

## Time and causality

Preserve original values, epoch, zone, precision and conversion rule. Windows event XML may
retain seven fractional decimal places; a microsecond-only conversion loses information.
Prefetch last-run values are internal execution metadata, whereas its filesystem times
describe the cache file. Unix text logs can lack year/zone; express an inferred value with
its basis and uncertainty. If the question asks for the displayed local time, answer that
representation and retain the UTC interpretation alongside it.

Compare clocks using events with a known common cause. Neither identical timestamps nor
small deltas prove a causal relationship. Filesystem standard-information and filename times
may differ after ordinary copies, restores, renames or metadata propagation. Compare content,
object lineage, journal sequence and neighboring activity before calling tampering. Matching
sizes and times alone cannot prove which source file was copied.

## Correlate identities that survive reuse

For Sysmon, prefer ProcessGuid with the originating host over PID alone. For telemetry that
has only a PID, add device identity, creation time and a bounded lifespan. Parent references
must point to the intended process instance; an estate-wide PID join is invalid.
Microsoft documents the correlation purpose of these fields in the
[Sysmon event contract](https://learn.microsoft.com/en-us/sysinternals/downloads/sysmon).

For authentication, carry host and logon/session identifier plus boot and time context.
Do not collapse multiple logons in one second. Session lifetime can help delimit possible
actions but a longer session is not automatically the malicious one. Bind follow-on events
to session identity where available; interval overlap alone remains circumstantial. Missing
logoff records imply an unknown end, not a zero-duration or indefinitely active session.

Differentiate account identity, declared workstation and network source. Machine accounts
can be relevant to an incident, but unexpected NTLM or a name/address mismatch does not by
itself identify a relay mechanism. Correlate target resource, directory/service relationship,
authentication path and follow-on effects before attributing a technique.

## Windows execution and persistence distinctions

Read EventID together with provider and the direct fields of that event. An event's category
number is not a task name. Registration, update, launch, completion and deletion are separate
scheduled-task facts. Reconcile task definitions with registry cache and event history;
one missing representation can also reflect collection timing, corruption or version behavior.
Task XML retained by audit events may preserve an action after the definition was removed.

An execution artifact has version-dependent semantics and retention. Prefetch counts are
artifact counters, not automatically the total number of executions in an investigation
period. Amcache and compatibility data need schema-specific interpretation. LNK, jump-list,
activity history and recent-file records contain different path forms; retain UNC paths,
volume identity and extensions until the question is resolved. Shell or folder navigation
records are not proof that a document's content was read.

Recover dirty registry hives only on copies with the corresponding transaction logs.
Determine replay order from sequence metadata rather than filename suffix. Document recovery
limits and verify a known record from the expected period. Do not silently merge an older
hive with logs from another snapshot.

## Configuration review without exercising an attack

For privileged services, assess effective rights of the specific identity, including direct
and group ACEs, deny entries, inheritance and token context. Inspect service configuration,
executable and parent-directory controls independently. Directory replacement rights can
matter even when a file's own ACL looks restrictive. Record the exposure and recommend a
supported least-privilege fix; do not modify objects to demonstrate exploitation.

When command parsing is relevant, inspect the deployed executable-path and argument rules,
quoting and access controls. A space in an unquoted path is not enough to establish a
reachable unsafe launch. Avoid declaring exploitability from a string-only scan.

Filenames that resemble options, surprising argv, or reads outside an expected application
root can indicate argument-handling abuse. The application may perform an unexpected action
without a shell or child process. Correlate process arguments, file-access evidence and
application authorization decisions; names alone also have legitimate uses. Investigate
existing traces and recommend unambiguous argument handling without constructing a payload.

## Trusted views and hidden activity

A live directory listing and a direct metadata lookup can disagree because of hooks, races,
permissions or corruption. Check an offline filesystem view and loaded-library/process
context before attributing concealment. A compromised kernel can contaminate all live views.
A service intrusion can leave neither a crash nor an extra process; a clean process tree
cannot substitute for missing memory, connection or file-access coverage.

For network-usage and file-count questions, define the root, object kinds and units. Exclude
filesystem metadata only when the question excludes it; publish the exclusion rule. Decimal
KB and binary KiB yield different values. Preserve byte counts and specify rounding.

The deliverable is a claim/evidence table and timeline with original coordinates, supported
meaning, alternatives, coverage and consequential gaps. Pass actionable scoping pivots to
the owner while retaining raw credentials and recovered personal content in private storage.
