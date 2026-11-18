---
name: soc-cloud-identity-forensics
description: Reconstruct cloud and identity activity from CloudTrail, Entra, M365, Okta, GCP or Kubernetes audit data, with explicit identity, outcome and counting rules.
---

# Cloud audit investigation

Use provider records to connect an action to a credential, delegated session, resource and
recorded result. Cloud workloads may also need endpoint or network evidence; audit logs are
not an exhaustive substitute for those sources. Establish tenant/account, region, log types,
retention and export completeness before analysis.

## Select a schema before joining records

- CloudTrail identity, session and storage activity: [AWS](references/aws-cloudtrail.md).
- Sign-in, consent, mailbox and identity-provider activity: [Entra, M365 and Okta](references/entra-m365-okta.md).
- Google service audit and cluster API actions: [GCP and Kubernetes](references/gcp-kubernetes.md).
- Exact totals, deduplication and transfer claims: [population rules](references/exact-populations.md).

Require a bounded JSON/export reader or an approved read connection that can retain raw
records and pagination diagnostics. Identify compression and expansion limits before parsing.
Missing parsers, inaccessible regions and capped exports are distinct blockers.
The [artifact reader](../../docs/artifact-tools.md) can classify a bounded, uncompressed
CloudTrail JSON export; its supplied-file population is not a provider coverage guarantee.

## Preserve identity layers

Record the emitted principal identifier, identity type, credential reference, session, issuer
and any evidenced originating identity as separate fields. A display name can change and an
account ID describes a broader scope than an individual. In a role session, sessionIssuer
identifies the issuing role; it does not automatically reveal the person who assumed it.
Use matching token-issuance records and provider-supported source identity for that link.
[AWS identity semantics](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-event-reference-user-identity.html)
provide the field contract; preserve unresolved delegation rather than filling it by proximity.

## Build the population and causal chain

Define interval endpoints, event category, authentication class, action, outcome and stable
event key before counting. Retain unknown and malformed candidates in a separate tally.
Repeated ingestion is not repeated activity. An error field, an authentication outcome and
an API acknowledgement can describe different stages; use the specific service contract.
Do not treat every event without an error field as proof the intended operation completed.

Follow changes in credentials, permissions, trust, applications, data access and logging.
Compare each change with its initiator, change authority, resulting configuration and later
use. A logging reduction affects visibility, but other trails or sensors may remain active.
A burst of denied MFA followed by success is a lead requiring session/source correlation and
user context. Denials without success still matter as attempted abuse; they do not establish
successful compromise. Shared addresses and token refreshes can distort the sequence.

Return the supported action chain and exact counts with inclusion/exclusion rules, observed
versus derived resource names, unresolved actors, evidence coordinates and coverage limits.
Avoid publishing raw keys or tokens. Remediation proposals identify which credentials,
issued sessions, trusts and permissions need review; execution remains an owner decision.

## Field lookup before flattening

Use the [CloudTrail and S3 field map](references/aws-cloudtrail.md) for credential and object pivots,
[identity-provider schema map](references/entra-m365-okta.md) for Graph, Sentinel, mail audit and Okta,
and [GCP/Kubernetes records](references/gcp-kubernetes.md) for API requests and workload context.
The [count worksheet](references/exact-populations.md) specifies which missing fields obstruct
an exact result. Keep nested source fields alongside display names when making the first timeline.
