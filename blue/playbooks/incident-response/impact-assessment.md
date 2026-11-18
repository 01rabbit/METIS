# Quantify impact without merging facts and estimates

Use this decision guide with the [response contract](../README.md). It is independently authored guidance; organization-specific exercise and approval are still required.

## Entry condition

The incident owner needs to prioritize response, explain business effects or assess notification obligations.

## Responsibilities

Technical analysts bound observed effects; asset and data owners supply business meaning; legal/privacy determines obligations; leadership decides accepted operational risk.

## Work and decision records

1. Build separate populations for confirmed affected, plausibly exposed and not yet assessed assets, accounts and data. Record the criterion and evidence for membership.
2. Distinguish confidentiality, integrity and availability effects. Access capability is not observed access; access is not necessarily delivery; encryption is not proof of exfiltration.
3. Define counting units before aggregation: objects, files, identities, records, sessions and bytes can produce different totals. Deduplicate by the correct stable key and preserve raw counts.
4. Estimate exposure windows using event and collection uncertainty. Avoid treating first observed activity as the proven beginning of the incident.
5. Map technical effects to dependencies, service interruption and data sensitivity with the relevant owner. Provide ranges or scenarios when exact losses are not established.
6. Update the assessment as scope changes and preserve prior estimates with their assumptions. Supply facts early for notification review without asserting a universal legal deadline.

## Completion evidence

The assessment labels each quantity as measured, estimated or unknown, provides its time and population bounds, and identifies the decision it supports. It includes potential collateral harm from proposed response actions.

## Tabletop check

Test duplicated cloud events, a query that returned fewer rows than requested, unreadable encrypted data and an asset with no telemetry. Ensure unknowns do not disappear from totals or become zero.

## Concrete observation contract

For each asset or data class, record confidentiality, integrity and availability effects
separately, with affected unit, numerator, population/denominator, time interval and
evidence locator. Distinguish observed records/files/accounts from estimated exposure and
capability to cause harm. Unknown scope is an explicit value, not zero impact or a
fabricated high-confidence total.

Apply the organization's versioned impact/priority rubric and name the business owner
who confirms service criticality. Dependency effects, containment disruption, recovery
cost and verified permanent loss are different measurements. Preserve the assumptions
behind extrapolation and revise estimates without erasing earlier decisions. A sensitive
system being reachable is not proof that its data was read; a service's return to health
does not show that confidentiality or integrity effects were resolved.
