# Check whether privileged execution has an authorized origin

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Was a privileged process expected for this login identity, session and approved task?

## Evidence to request

Login UID, real/effective IDs, audit session, process ancestry, sudo/polkit or equivalent policy decisions, file ownership/mode/capabilities and the approved administrative task.

## Reasoning procedure

- Distinguish login attribution from current privilege. A root effective UID does not imply a root login, and a missing login UID may identify a daemon context.
- Correlate elevation and execution within a justified interval using session and process lineage. An earlier authorized command does not authorize every later action in a long session.
- Inspect the executable and policy that enabled the privilege transition. Interpreter names and common administration tools have many legitimate uses.
- Review changes to privileged executable metadata and elevation policy as separate evidence. Set-user-ID behavior need not be accompanied by a user-space setuid call.
- Bound the finding to unauthorized privilege use when policy evidence supports it; do not claim a kernel flaw without distinct evidence.

## Alternatives and limits

Interactive administration, installation, backup and service startup commonly run with elevated identities. Audit architecture filters and container namespaces can hide or reinterpret identity fields.

## Discriminating checks

Test an approved elevation, a daemon root process, a stale session association and unexpected privileged execution. Confirm architecture and UID semantics with inert records. Changing elevation rules or terminating administrative sessions requires a scoped grant.

## Concrete observation contract

Inspect sudo logs for `TTY`, `PWD`, target `USER`, `COMMAND` and the recorded outcome.
Permitted and denied attempts may both be logged. Where present, audit `USER_CMD` content
can be encoded; preserve the raw record and decode for analysis without execution.
`SYSCALL` success/exit and `EXECVE` records supply separate evidence that a process ran,
with `auid`, `uid`, `euid`, `ses`, `pid`, `ppid` and `exe` identifying its context.

Review the effective `/etc/sudoers` policy and includes such as `/etc/sudoers.d/`,
including host/user scope and file ownership. A broad permission or a dual-use binary's
name is a configuration lead, not proof of privilege misuse. The unset audit identity
must remain unknown rather than being converted to UID 0. A denied request, a legitimate
administrative command and an observed unauthorized privileged effect require distinct
outcomes; no privilege-escalation recipe is part of validation.
