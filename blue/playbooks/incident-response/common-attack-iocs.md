# Evaluate indicators as scoped evidence

Use this decision guide with the [response contract](../README.md). It is independently authored guidance; organization-specific exercise and approval are still required.

## Entry condition

A case begins with an address, domain, hash, account, filename or other indicator that needs validation and expansion.

## Responsibilities

The investigator owns evidence quality; the intelligence owner manages source reliability and sharing restrictions; the response owner decides blocking or containment.

## Work and decision records

1. Preserve where the indicator came from, its timestamp, confidence, intended scope and any sharing restriction. An unattributed list has weaker evidential value than a traceable observation.
2. Normalize according to the indicator type while retaining the original representation privately. Domain case, URL encoding, IP family and file-hash algorithm have different semantics.
3. Determine what a match proves. A hash identifies acquired bytes; a shared address can represent many services; a filename is readily reused; a network lookup is not a completed connection.
4. Correlate matches with asset role, process/user context and observed effects. Many matches from one upstream source are not independent confirmation.
5. Bound negative results to actual retained data and parser/query success. Expired indicators, address reassignment and missing collection can explain non-hits.
6. Promote reusable lessons as independently written analytical methods. Do not copy case-specific indicator sets, private reports or raw logs into the knowledge library.

## Completion evidence

The result identifies confirmed matches, their meaning, attribution limits and the next discriminating observation. A block proposal includes current ownership, collateral impact and review/expiry conditions.

## Tabletop check

Test a shared hosting address, an outdated domain, a matching acquired hash and a filename-only hit. Verify that each produces a different strength of conclusion and that no sample is uploaded for enrichment.

## Concrete observation contract

Preserve indicator type and representation: hash algorithm plus digest; domain versus
URL; IP with observed port/protocol/direction; or file path with host and acquisition
context. Attach event time, validity interval, source confidence and the observation
locator. A path or process name is not a global artifact identifier.

For endpoint association, use Sysmon `ProcessGuid` with the originating host. In
Defender `DeviceProcessEvents`, use `DeviceId` with `ProcessUniqueId`; an initiating
process in a file or network event is named by `InitiatingProcessUniqueId`. Those two
process fields describe different roles and have string values. Confirm platform/sensor
availability; fallback PID joins require device scope and process creation time. Use the
[native Defender field map](../../skills/soc-siem-hunt/references/sentinel-kql.md) to
select the table and clock before joining. For network evidence,
retain the connection tuple/UID and DNS transaction context instead of resolving a domain
today and assuming the address was the same historically. A matching indicator narrows
scope but does not establish actor, execution or successful effect. Record shared
infrastructure, expired indicators and legitimate administration as explicit alternatives.
