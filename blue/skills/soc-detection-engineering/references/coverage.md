# Defensive investigation coverage

Coverage is an evidence question with sensor requirements, not deployed or validated
protection. See the [catalog](../../../detections/README.md) and
[validation guidance](validation-integrity.md).

| Area | Evidence and limits |
| --- | --- |
| Kernel modules and memory safety | Module provenance, crashes, credentials and memory; mitigations alone do not establish execution. |
| Firmware, boot and netboot | Boot state, configuration, firmware digest and provisioning; filesystem monitoring cannot see all pre-OS changes. |
| Memory loaders and anti-analysis | Executable regions, thread origins, API resolution and memory strings; baseline JITs and security products. |
| Authentication relay and directory abuse | Authentication, certificate enrollment and directory changes; a successful login alone does not identify the mechanism. |
| DNS and ICMP channels | Full protocol fields, distribution, direction and host process; summary logs can omit the relevant field. |
| DLL, service and task persistence | Search paths, permissions, configuration, task actions and lineage; writable paths alone are not observed abuse. |
| Injection and deserialization | Application sink/error telemetry and host effects; access logs often show only attempts. |
| Browser scripts and data exposure | Application audit, outbound channel, stored-data access and CSP; data can leave through the app's own origin. |
| Cookies, sessions and logic flaws | Auth decisions, session lineage, object authorization and reauthentication; requests can be well-formed yet unauthorized. |
| Debug, source and build exposure | Responses, dev configuration and access audit; errors may contain private secrets. |
| Mail, arguments and options | Actual argv, template drift, file effects and app logs; harmful operations need not spawn children or crash. |
| Template, expression and type semantics | Version-specific errors and authorization outcomes; marker matches do not prove execution. |
| Routing and object access | Virtual host, redirects, internal egress and object decisions; SSRF and IDOR need distinct evidence. |
| GraphQL and signing APIs | Operation counts, alias/batch size, response volume and identity; request rates can conceal many operations. |
| Control systems and buildings | Read/write functions, interlock state and passive traffic; reservation identifiers are not authenticated identities. |
| Physical interfaces and vehicles | Access records, firmware and bus timing; SPI/JTAG reads and CAN may lack sender attribution. |
| Radio and space links | Frame boundaries, timing, sequence and checksum scope; error detection is not origin authentication. |
| Untrusted telemetry and AI | Input provenance, tool authorization and audit; descriptions alone do not enforce boundaries. |
| Packaged applications and containers | Embedded resources, engine bundles, layers and config; deleted top-layer files can survive in older layers. |
| Sandboxes and process boundaries | Isolation controls, transitions, file/network access and policy decisions; no crash is not proof of safety. |
| Disclosure and memory faults | Response content, crash/memory evidence and file access; disclosure alone does not prove exploitation. |

Use these subjects for analysis, hardening and regression detection. Exercise identities,
answer strings, attack recipes and inherited validation scores are excluded.

## Choose an observable schema

Use [Windows events](telemetry-windows.md) for process/logon/directory/service/task
identities, [Linux and network records](telemetry-linux-network.md) for audit serials,
capabilities and flow/transaction joins, [application and identity records](telemetry-application-identity.md)
for HTTP/database/mail/cloud decisions, and [specialist records](telemetry-specialist.md)
for platform, crash, industrial and wireless evidence. Their provider/version and
collection prerequisites apply before a card's predicate can be evaluated.

The broader subjects in the table are investigation prompts, not an assertion of
dedicated parsers, event coverage or validated rules for every platform. Where no concrete
collector/schema is supplied, record that engineering gap and request the authoritative
platform documentation. Do not synthesize field names or operational test results to fill it.
