# Remove established control paths and restore service with evidence

Use this decision guide with the [response contract](../README.md). It is independently authored guidance; organization-specific exercise and approval are still required.

## Entry condition

Containment has reduced immediate harm sufficiently to plan removal and controlled return to service; investigation may still discover additional scope.

## Responsibilities

Technical owners implement approved changes. The incident owner coordinates dependencies. The business/service owner accepts residual risk and authorizes return to operation.

## Work and decision records

1. List confirmed and suspected control paths: affected software, persistence, credentials, tokens, trust relationships and management infrastructure. Removing one artifact is not proof that access is gone.
2. Choose remediation appropriate to trust loss: repair, rebuild or replacement. Preserve necessary evidence before destructive changes, balancing operational urgency.
3. Plan credential/key/session changes in dependency order. Revoke active access where applicable and verify that new secrets are not exposed through still-compromised systems.
4. Validate restore sources, configuration and data integrity. A successful backup job is not proof that its contents are clean, complete or recoverable.
5. Return services in controlled stages with functional tests, security observations and rollback criteria. Check upstream/downstream dependencies and user impact.
6. Monitor for recurrence for a risk-based period with defined coverage and owners. New evidence reopens scoping and may require renewed containment.

## Completion evidence

The recovery decision records what was remediated, how it was checked, remaining trust assumptions and who accepted service risk. Continued monitoring and unresolved improvements remain assigned after case closure.

## Tabletop check

Exercise a clean application restored with an exposed account still active, a backup integrity failure and recurrence during staged recovery. Verify that “service available” and “adversary access removed” are separate acceptance tests.

## Concrete observation contract

Maintain a control-path inventory with artifact/object ID, host or tenant, observed state,
provenance, authorized change, verification result and remaining uncertainty. Relevant
locations depend on established evidence: Windows service configuration and scheduled
tasks; Linux cron/systemd units and account `authorized_keys`; directory permissions and
identity/session state. These are inspection categories, not proof that every system has
each persistence mechanism or that a listed file is malicious.

For recovery, preserve backup/source identity and digest where meaningful, restore job
ID/result, restored asset/version, functional tests, security configuration checks and
monitoring coverage. A completed restore job does not prove a trustworthy state. Keep
identity exposure and application/data restoration as separate acceptance tracks, with
residual risk approved by the responsible owner. An unavailable backup or unverified
control path remains open even when the service answers health checks.
