# Classify an incident without mistaking labels for evidence

Use this decision guide with the [response contract](../README.md). It is independently authored guidance; organization-specific exercise and approval are still required.

## Entry condition

An event needs routing, severity and a shared description across analysts and business owners.

## Responsibilities

The owner maintains the working classification; the incident commander approves operational severity; specialist analysts validate technical claims within their evidence.

## Work and decision records

1. Classify the observed behavior and affected boundary independently from the suspected cause. Examples include unauthorized account use, data disclosure, destructive modification and service disruption.
2. Track status separately: lead, suspected incident, confirmed incident, contained, recovery and closed describe response state rather than technique.
3. Record confidence, impact and urgency as separate dimensions. One severity label cannot express all three.
4. Use technique or weakness mappings only where the evidence supports their definitions. A missing control is not an observed technique, and a responder action is not attacker behavior.
5. Allow multiple linked categories when one incident has several effects, while avoiding duplicate case counts.
6. Revise classifications transparently when evidence changes. A change from suspicion to benign activity is an analytical result, not a failure to hide.

## Completion evidence

The label routes work and communicates priority while leaving the underlying evidence and uncertainty visible. No actor attribution, exploit success or impact is inferred merely from the chosen category.

## Tabletop check

Exercise a denied login burst, an approved bulk export, confirmed unauthorized access with unknown data impact and a logging outage. Check that these remain distinct even if they share a dashboard rule.

## Concrete observation contract

Keep distinct fields for observed behavior, suspected mechanism, incident category,
severity/priority, affected asset class, business impact and confidence. The vocabulary
and priority thresholds come from the organization's versioned policy; an ATT&CK label
is not a severity number or proof of the mechanism. Retain the evidence locator and
reviewer/time for each change of classification.

Use separate outcomes for confirmed unauthorized activity, benign activity explained by
evidence, and unresolved assessment. A closed analytical task can still have an
inconclusive incident classification. Track the collection/coverage gap that prevents a
decision, with an owner for the next evidence check. A low-impact posture weakness and
an observed harmful action should not be merged merely because they share a technique
label; urgent action can be justified without settled actor attribution.
