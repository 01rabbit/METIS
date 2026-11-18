# Assess suspicious database activity attributable to an application request

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Does database evidence support unauthorized query behavior or data access associated with untrusted input?

## Evidence to request

Application request/trace IDs, connection-pool session context, database audit outcome and object access, query fingerprints, account/source baselines and export metadata.

## Reasoning procedure

- Begin with account permissions and normal query families. Catalog inspection, unions, bulk operations and large reads can all be expected application behavior.
- Separate syntax failures from successful execution. An error containing unusual input proves at most that a parser encountered it; it does not establish unauthorized access.
- Where connection pooling prevents a direct user mapping, state the attribution boundary. A service account is not a reliable stand-in for an individual requester.
- Use object sensitivity, result volume, timing and an attributable request to distinguish a suspicious query from a deployed migration or reporting task.
- Report returned rows, result delivery and external transfer separately. An executed query does not prove that the client received all results.

## Alternatives and limits

ORM initialization, BI tools, schema migrations and backup jobs are major alternatives. Audit facilities may omit successful reads or truncate statements; negative conclusions require checked coverage.

## Discriminating checks

Test a legitimate catalog reader, a deployment syntax error, an interrupted result stream and an unexpected sensitive-object read with a valid trace link. Compare counts after duplicate removal. Permission or query-rule changes require application/database-owner authority.

## Concrete observation contract

For SQL Server audit, preserve `action_id`, `event_time`, `session_id`, database/object
and principal fields; map `connection_id`/`client_ip` only where supported. For non-login
events, `succeeded` means the permission check succeeded, not that rows were returned or
data changed. A claimed row count requires a real execution/application source; it is
not a guaranteed generic audit column.

With PostgreSQL CSV logging, retain the deployed layout and use `session_id` plus
`session_line_num` with `process_id`, `sql_state_code` and `application_name`. A syntax
error and another request's successful result must not be merged. Bind a pooled database
session to the application's request/actor through trace evidence and transaction scope.
Use completed operation or acquired data-state evidence for a successful-effect claim;
ordinary reporting workloads and authorized bulk exports are relevant counterexamples.
