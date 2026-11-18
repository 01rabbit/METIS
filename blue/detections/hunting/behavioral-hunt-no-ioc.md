# Develop an investigation without a known indicator

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Which behavior would be unexpected for this asset and identity population, and what evidence could disprove the hypothesis?

## Evidence to request

Asset and role inventory, representative endpoint/network/identity telemetry, collection quality, peer-group definitions and approved operations.

## Reasoning procedure

- State the protected behavior or privilege boundary before selecting tools or query syntax. Choose evidence that observes that boundary rather than merely unusual names.
- Compare an entity with relevant peers and its own history. Fleet-wide rarity mixes incompatible populations and can elevate every new deployment.
- Inspect the highest-information examples, then test a benign explanation using independent data. Record changes to the hypothesis rather than silently moving the goalposts.
- Carry platform-specific field semantics into the normalized model. An event category from one EDR is not automatically equivalent to a similarly named field elsewhere.
- Close with supported observations, unresolved coverage or a new detection proposal; lack of a known indicator is not a reason to label activity benign.

## Alternatives and limits

New software, small peer groups, seasonal jobs and incomplete inventory produce rare events. A compromised but prevalent management tool may not be rare at all.

## Discriminating checks

Test the method against an approved rollout, sparse telemetry and an unusual but authorized administrator. A useful hunt output includes its denominator, counterexamples and a reproducible event selection rather than only a compelling narrative.

## Concrete observation contract

Record the peer-group definition, role membership source, observation interval and
reporting coverage before computing a behavioral baseline. Use host/process entity keys
and parent relation from the mapped provider; grouping by executable basename alone can
merge unrelated applications. Compare the same host's history and its role cohort, with
newly enrolled or changed-role devices marked separately.

The sample size, distinct-device count and missing telemetry belong beside the score.
Do not replace an absent baseline with zero frequency. A legitimate deployment or
scheduled batch workload must be represented in the benign examples. Preserve the
specific deviation and its observed downstream effect as separate facts; a model score,
rare chain or absence of a known indicator cannot by itself establish an incident.
