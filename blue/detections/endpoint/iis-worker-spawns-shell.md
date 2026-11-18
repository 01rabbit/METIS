# Investigate unexpected work launched by an IIS worker

Status: analytical design; local sensor/backend validation is pending. Apply the [review and deployment contract](../README.md) before turning a candidate into an alert.

## Investigation question

Is a web worker starting a command processor or utility outside the application design?

## Evidence to request

Worker process entity, application-pool identity, child ancestry, command metadata, application request IDs, deployment records, filesystem and outbound connections.

## Reasoning procedure

- Resolve the worker to the correct application pool and site; many services share executable names on one host.
- Trace the child and descendants using process identities rather than only parent PID. Include brokered execution when direct parentage is absent.
- Relate the launch to an attributable request, job or deployment. A suspicious child is a process observation, not automatic evidence of a web shell.
- Inspect resulting files, privileges and network activity to bound impact. A service identity may have access beyond the site directory.

## Alternatives and limits

PDF generation, image conversion, deployment hooks, backup and monitoring can launch utilities. A normally quiet application may legitimately add such functionality in a release.

## Discriminating checks

Test a documented conversion job, a deployment-time child and an unexplained child with a valid request correlation. Preserve request/worker separation during pool recycling. Isolating a shared host needs service-owner impact assessment.

## Concrete observation contract

Locate the configured IIS site log, commonly
`%SystemDrive%\inetpub\logs\LogFiles\W3SVC{site-id}\u_ex*.log`, and preserve its
`#Fields` header. Request method/path/query, status/substatus, client address and
`time-taken` locate the web observation; they do not bind it automatically to a worker
process. Request/trace ID, site-to-application-pool mapping and worker lifetime are needed
when multiple requests or recycled workers overlap.

Sysmon 1 can bind `ParentProcessGuid` to the correct `w3wp.exe` instance and identify
the child. Security 4688 instead needs decoded PID plus creation time and creator fields.
Relate file/network effects separately. A HTTP 200 and a child process in the same minute
are insufficient to name a causal request; a legitimate rendering/export helper and an
application-pool recycle should be included in benign/incomplete fixtures.
