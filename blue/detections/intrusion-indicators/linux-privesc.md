# Review writable execution paths and Linux privilege boundaries

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Can an unprivileged identity influence a privileged execution path, and is there evidence that it did?

## Evidence to request

Scheduled-job/unit inventory, referenced scripts and directories, ownership/ACLs/mode/capabilities, file-change audit, effective process identities and elevation decisions.

## Reasoning procedure

- Resolve each privileged job to the actual executable, scripts and writable path components. A world-writable unrelated file is not an exploitable job dependency.
- Compare metadata and content changes with later privileged execution. File writability is a weakness; unauthorized modification and execution are separate observations.
- Review file capabilities in relation to the application and policy. The presence of a capability does not prove it was used to obtain broader privilege.
- For scheduled contexts, a missing login UID may be normal. Keep daemon/cron activity separate from human sessions.
- Inspect approved elevation decisions and their bounded relationship to execution rather than treating one earlier approval as authorization for an entire session.

## Alternatives and limits

Package installation, administrator automation and container runtime setup legitimately change privilege-related metadata. Raw audit path records need event reconstruction and may not contain every desired capability field.

## Discriminating checks

Test an approved maintenance job, a writable file never executed, capability metadata with no observed use and an attributable unauthorized modification. Do not execute privileged paths to prove weakness. Policy repair belongs to the system owner.

## Concrete observation contract

For scheduled activity, inspect the acquired `/etc/crontab`, `/etc/cron.d/` and configured
per-user spool, commonly `/var/spool/cron/`. Record the job owner, referenced path, file
owner/mode, writable ancestor directories and the effective configuration at execution
time. A writable reference is an exposure finding until actual execution is observed.

Reconstruct auditd `SYSCALL`/`EXECVE`/`PATH`/`CWD` records by host plus audit timestamp and
serial. Compare `auid` with `uid`/`euid`, and the affected PATH `name`, `inode`, `dev`,
`mode`, `cap_fp`, `cap_fi` and `cap_fe` when present. Capability metadata on a file does
not assert that a process acquired or used it. Relate execution to its parent and an
observed privileged effect. [Linux telemetry](../../skills/soc-detection-engineering/references/telemetry-linux-network.md)
defines the raw join, unset audit identity and distribution-specific source paths.
