# Trace unusual SQL Server actions across database and operating system

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Can a database action be linked to unexpected host execution, privilege use or access to another database server?

## Evidence to request

Database audit records with session/principal, configuration changes, effective permissions and client identity; SQL service process ancestry; network flows; scheduled jobs and linked-server inventory.

## Reasoning procedure

- Investigate an interpreter launched under the engine process, then identify the initiating database session where available. Do not equate the service account with the human or application requester.
- Record configuration changes and their previous values. Feature availability is a capability change, not evidence that a command was executed.
- For remote database access, follow client and server sessions on both sides. Outbound traffic on a common SQL port can be replication or monitoring; instance ports can differ.
- Review impersonation and linked-server mappings against effective privileges. A principal change in one session does not prove compromise of a second server.
- Bound result-set/export evidence to observed objects and bytes rather than treating query execution as completed extraction.

## Alternatives and limits

Backup, maintenance, ETL and monitoring workflows legitimately create child processes or remote sessions. Host ancestry can be absent for out-of-process components. Database audit completeness depends on the configured action groups.

## Discriminating checks

Use synthetic audit/process events for a maintenance job, an enabled-but-unused feature, and an attributable unexpected child process. Confirm that cross-server attribution requires a valid session bridge. Configuration rollback is a separately approved change.

## Concrete observation contract

Request SQL Server audit rows with `event_time`, `action_id`, `session_id`, principal,
database, schema and object context. Preserve `client_ip`, `application_name` and
`connection_id` where that version/action provides them. `statement` can be sensitive and
may not contain substituted parameter values. In non-login audit events, `succeeded`
reports permission checking, not completed data access or an operating-system effect.

If a SQL service process has an unexpected descendant, bind Sysmon 1 `ParentProcessGuid`
to that particular service lifetime and collect the child's file/network outcomes. A
database session is not interchangeable with a process ID; an application trace or
audited operation relationship must connect them. Connection pooling and approved
maintenance jobs are counterexamples. Use [application telemetry](../../skills/soc-detection-engineering/references/telemetry-application-identity.md)
for schema and outcome distinctions before declaring a server-side effect.
