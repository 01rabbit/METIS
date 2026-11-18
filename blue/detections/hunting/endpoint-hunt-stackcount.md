# Use endpoint prevalence without confusing rarity with compromise

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Which process relationship or persistent configuration is unusual among genuinely comparable devices?

## Evidence to request

Process parent/child identities, service/autorun state, executable hashes and signer evidence, asset roles, installed software and telemetry coverage per device.

## Reasoning procedure

- Define a peer group and minimum observation coverage before ranking rarity. Count distinct reporting devices rather than total event rows.
- Review parent-child relationships, persistent launch paths and signer facts as separate features. Each has a different denominator and missing-data behavior.
- Distinguish absent signature collection, an unsigned artifact and an invalid signature. They must not collapse into one suspicious category.
- Inspect representative underlying events and deployment context. One outlier can be an approved specialist workstation; a widespread malicious artifact may look common.
- Retain small-population uncertainty rather than assigning a strong severity from a tiny group.

## Alternatives and limits

New builds, software migrations, infrequently used applications and mixed device roles cause unstable rankings. Repeated crashes or forwarding duplicates inflate event-based counts.

## Discriminating checks

Test mixed peer groups, duplicate rows, an uninstrumented device and a known one-off application. Ensure missing signatures remain unknown. Convert a useful hunt result into a detection only after a measured local precision review.

## Concrete observation contract

Define the population before stacking frequency: asset role, eligible devices, actually
reporting devices and the observation interval. Count distinct `DeviceId` or `host.id`,
not the number of duplicate events. A missing device is unobserved rather than evidence
that the behavior did not occur. Preserve the executable hash algorithm, normalized path
and process entity separately; equal filenames need not identify equal binaries.

For Defender process records, use `ProcessUniqueId`/`InitiatingProcessUniqueId` for
lineage. Child version information and parent signature fields do not establish the
child's signature. Join the relevant SHA-1 and device to `DeviceFileCertificateInfo` for
`IsSigned`, `IsTrusted`, `Signer` and `Issuer` where observed. A rare signed helper on
a newly deployed role and an unsigned internal build should challenge any simple
rarity-equals-malicious rule.
