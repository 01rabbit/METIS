# Investigate interpreter execution in a Linux service context

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Does a daemon launch an interpreter or utility outside its expected service workflow?

## Evidence to request

Process ancestry, executable path/hash, effective and login identities, service/container identity, audit records, unit configuration and approved service jobs.

## Reasoning procedure

- Identify the service role first. A web daemon, scheduler and SSH daemon have very different expected child behavior.
- Reconstruct one audit operation by its event identity; SYSCALL, EXECVE and PATH fragments are parts of one event, not independent executions.
- Resolve ancestry from a valid process history. A raw parent PID does not itself contain the parent executable and may be reused.
- For SSH-related shells, bind the process to an authentication/session record before investigating subsequent activity. Accepted login does not identify the original person behind a bastion.
- Include service identity and filesystem/network effects when prioritizing an unexplained child.

## Alternatives and limits

Maintenance scripts, hooks, health checks and scheduled jobs can be ordinary service behavior. Container PID namespaces and missing process-start history can break host-level ancestry.

## Discriminating checks

Test a normal scheduler child, an authenticated SSH shell and an unexplained service child. Ensure multi-record audit events produce one execution. Do not convert every daemon shell into an intrusion verdict; response actions need owner authorization.

## Concrete observation contract

Request the configured audit stream, often `/var/log/audit/audit.log`, and relevant
journal records. Use `_SYSTEMD_UNIT`, `_PID`, `_UID` and `_BOOT_ID` to identify the
service context. Reconstruct audit records before comparing `pid`, `ppid`, `exe`, `comm`,
`uid`, `euid`, `auid` and `ses`. Raw auditd does not have a universal `ParentImage`; resolve
the parent's executable through its bounded process history.

A daemon's unset audit login identity is common and does not establish an interactive
root user. Bind the resulting shell to the service instance and the triggering request
or approved maintenance action where available. A shell string inside an argument does
not prove a shell process existed. Namespace/container identity and service restarts
constrain PID joins. Check successful child execution and its observed effects while
retaining approved wrappers and diagnostic helpers as alternatives.
