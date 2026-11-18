# Review Windows execution trust paths and privileged outcomes

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Has a lower-privilege principal changed something later used by a higher-privilege process?

## Evidence to request

Service/task configuration, executable and directory ACLs, file/module changes, process tokens and ancestry, relevant object-access events and change records.

## Reasoning procedure

- Inspect service configuration permissions and binary-directory writability separately. A configuration edit and an on-disk replacement have different evidence trails.
- For ambiguous service paths, determine actual resolution and permissions. Missing quotation marks alone do not prove an exploitable or exploited condition.
- For module loading, establish the loaded path/hash and trust decision. An unusual DLL path can be a configuration issue without proving a search-order hijack.
- For scheduled tasks, retain action, principal and execution outcome. Registration does not prove the task ran with the requested privilege.
- Assess unexpected privileged descendants or token transitions with source-session context. Named-pipe events or service identity alone cannot establish a token-abuse mechanism.

## Alternatives and limits

Installers, management software, maintenance tasks and application plugins frequently cross these boundaries legitimately. ACL inventory collected after the incident may differ from the state at execution.

## Discriminating checks

Test an approved installer, writable-but-unused path, task registration without execution and an attributable unauthorized privileged result. Do not reproduce elevation. Repair and service interruption require an asset-owner decision.

## Concrete observation contract

Resolve process context with Sysmon 1 or Security 4688, retaining identity, creator and
integrity/token context where available. Service installation can appear as Security
4697 or Service Control Manager 7045 in System; task registration/update as Security
4698/4702. Their existence records configuration, not execution. Parse 4698 `TaskContent`
or 4702 `TaskContentNew` for principal, action and run level without treating requested
privilege as achieved.

Correlate the configured executable or module with a later process or image load and
its real file identity/ACL. Sysmon 11/13 supply selected file/registry mutations; 17/18
supply named-pipe activity, which alone does not establish privileged impersonation.
[Windows telemetry](../../skills/soc-detection-engineering/references/telemetry-windows.md)
describes audit prerequisites and PID lifetime handling. Record legitimate service
deployment and an unexecuted configuration change as counterexamples.
