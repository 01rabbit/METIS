# Detection investigation library

These 59 investigation cards and two rule files support analyst reasoning. A card describes an evidence question, collection contract, competing explanations and discriminating checks. It is not a deployed detector or evidence that a backend query has been tested. No inherited performance claims or external rule code are retained.

## Review and deployment contract

1. Define the protected asset, observation interval and exact claim. Distinguish attempted activity, allowed capability, completed action and business impact.
2. Verify collection before interpretation: provider, enabled event classes, filtering, retention, missing hosts, timestamps, truncation, pagination and collector health. An empty result after a failed query is unknown.
3. Map fields from real retained examples. Preserve original event references and normalization decisions. Do not substitute similarly named fields without checking meaning.
4. Define the entity and denominator. Use process creation identity rather than PID alone, authoritative session bindings rather than account names alone, and distinct events rather than transport duplicates. Bound every time join.
5. Express the predicate and aggregation independently for the target backend. Keep a query hash/version, parameter values, expected matching event IDs and the exact collection scope. A search adapter working correctly does not validate a detector.
6. Exercise a positive inert fixture, a realistic benign alternative, a missing-field case, duplicates and a broken correlation. Then backtest approved retained telemetry with a measured review sample. Synthetic tests establish logic, not production precision.
7. Release only with named ownership, measured alert volume, coverage limits, expiration of exceptions and rollback. Tune using approved operations plus source/device context; a calendar window alone is not proof of authorization.

Record separately: design reviewed; syntax accepted; fixture results; retained-data validation; live sensor/backend validation; operational approval. A finding can be urgent before every hypothesis is resolved, but a strong conclusion still needs the evidence for that conclusion.

## Backend mapping worksheet

| Evidence role | Mapping questions |
| --- | --- |
| Process identity | Does the source provide a creation GUID/entity ID, host boot identity and parent identity? Is signature data collected in a different event class? |
| Web request | Are raw input, parsed values, response attributes and authorization decisions actually collected? What joins the proxy to the application? |
| Identity session | Does the event represent challenge, token issuance, session creation, resource access or revocation? Are interactive and noninteractive populations both visible? |
| Network connection | Is the record a new connection, a sampled flow, an active-flow export or one side of a NAT/proxy relationship? |
| Cloud operation | Is the identity an individual, assumed session or service? Does the event record intent, success and returned data separately? |
| SIEM time and counts | Which timestamp drives the interval, what is the ingestion delay, and are result limits or acceleration summaries changing the population? |

Splunk SPL, Sentinel/Defender KQL, Elastic queries, Sigma conversion, network rules and YARA have different data models. Translation requires a concrete source schema and backend test. Do not mechanically rename columns or advertise equivalent coverage. See [SIEM status](../docs/siem-support.md) for connector and validation boundaries.

ATT&CK labels describe supported behavior; they are not detection confidence or a finding of successful compromise. A posture weakness, missing log and incident-response action should not be mislabeled as an observed attacker technique. Check the current technique definition before adding a mapping.

## Response boundary

Analysts may read scoped evidence and prepare proposals. Blocking, quarantine, credential/session changes, rule deployment, device control and external messages require the applicable user authorization or existing owner grant described in [AGENTS.md](../AGENTS.md). Urgent ongoing harm should be escalated promptly; do not wait for perfect attribution or complete scoping before presenting containment options. Keep evidence copies, evaluation results and credentials in private case storage.

## Technical reference points

The following primary resources were consulted to verify particular definitions, not copied into this library:

- [Sysmon event semantics](https://learn.microsoft.com/en-us/sysinternals/downloads/sysmon): event IDs describe observations, and missing inferred thread/module fields are not a malware verdict. Registry-change events do not provide a registry-read feed.
- [Zeek connection records](https://docs.zeek.org/en/current/reference/logs/conn.html): connection fields require sensor and protocol context before aggregation.
- [Sigma rule specification](https://sigmahq.io/sigma-specification/specification/sigma-rules-specification.html) and [YARA PE module](https://yara.readthedocs.io/en/stable/modules/pe.html): syntax and model reference for the experimental rule files.
- [Session management guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html): cookie/session controls need application-specific interpretation.
- [FIRST TLP](https://www.first.org/tlp/): sharing restrictions must follow the originator and applicable label.

These resources do not validate METIS detections. Recheck product/version semantics before operational use.

## Investigation cards

### Advanced Intrusion Indicators

- [Review changes to Kerberos delegation trust](advanced-intrusion-indicators/ad-delegation-abuse.md)
- [Determine what an application-control decision actually enforced](advanced-intrusion-indicators/applocker-wdac-bypass.md)
- [Investigate access to credential-bearing resources](advanced-intrusion-indicators/lsass-credential-access.md)
- [Trace unusual SQL Server actions across database and operating system](advanced-intrusion-indicators/mssql-attack.md)
- [Assess proxy use and conflicting network identities](advanced-intrusion-indicators/network-filter-bypass-domain-fronting.md)
- [Corroborate suspected cross-process execution](advanced-intrusion-indicators/process-injection.md)

### Application

- [Separate application failures, information exposure and logging gaps](application/app-logging-and-error-exposure.md)
- [Assess session-cookie configuration and session continuity](application/cookie-and-session-flag-anomalies.md)
- [Link suspicious input to an observed backend consequence](application/injection-attempt-detection.md)
- [Distinguish endpoint discovery from actual exposure](application/security-misconfiguration-exposure.md)
- [Investigate session use that does not fit its authentication history](application/session-hijack-and-auth-anomaly.md)
- [Assess suspicious database activity attributable to an application request](application/sqli-confirmation-and-db-access-anomaly.md)
- [Follow unsafe markup from input to browser impact](application/xss-attempt-detection.md)

### Endpoint

- [Investigate unusual directory discovery](endpoint/ad-enumeration-ldap-recon.md)
- [Review durable changes to directory control](endpoint/ad-persistence.md)
- [Assess impaired script inspection](endpoint/amsi-bypass-defense-impairment.md)
- [Prioritize repetitive outbound connections](endpoint/c2-beacon-detection.md)
- [Assess whether DNS carries unusual application data](endpoint/egress-tunneling.md)
- [Design file-to-execution correlation in Elastic](endpoint/elk-detection-rules.md)
- [Investigate unexpected work launched by an IIS worker](endpoint/iis-worker-spawns-shell.md)
- [Evaluate unusual authentication and service-ticket use](endpoint/lateral-movement-pth-kerberoast.md)
- [Investigate interpreter execution in a Linux service context](endpoint/linux-daemon-spawns-shell.md)
- [Check whether privileged execution has an authorized origin](endpoint/linux-privesc-sudo-gtfobins.md)
- [Trace unexpected child execution from a Linux web application](endpoint/linux-webapp-to-shell.md)
- [Build an evidence graph across investigation stages](endpoint/multistage-killchain-correlation.md)
- [Investigate unexpected execution associated with a document application](endpoint/office-macro-spawn.md)
- [Relate script execution to newly written artifacts](endpoint/script-host-dropper.md)
- [Review service configuration and executable provenance](endpoint/service-anomalous-imagepath.md)
- [Correlate per-user launch configuration with elevated execution](endpoint/uac-bypass-registry-hijack.md)

### Foundations

- [Assess control-system commands against operational intent](foundations/ics-ot-protocol-and-command-anomaly.md)
- [Correlate message delivery, interaction and account effects](foundations/phishing-email-and-landing-detection.md)
- [Evaluate destructive file activity with corroborating context](foundations/ransomware-behavioral-detection.md)
- [Review wireless identity and management-frame anomalies](foundations/wireless-rogue-ap-and-deauth-detection.md)

### Hunting

- [Hunt for combinations that threaten recovery and data availability](hunting/actor-ttp-ransomware.md)
- [Develop an investigation without a known indicator](hunting/behavioral-hunt-no-ioc.md)
- [Investigate repeated authentication challenges and later identity use](hunting/cloud-hunt-azure.md)
- [Use endpoint prevalence without confusing rarity with compromise](hunting/endpoint-hunt-stackcount.md)
- [Run a bounded hypothesis-led investigation](hunting/hunt-methodology.md)
- [Report a hunt with explicit evidence and sharing boundaries](hunting/hunt-reporting-tlp.md)
- [Analyze connection timing in a coverage-aware network hunt](hunting/network-hunt-beacon.md)

### Intrusion Indicators

- [Investigate link and library artifacts as execution or access leads](intrusion-indicators/client-side-lnk-libraryms.md)
- [Review writable execution paths and Linux privilege boundaries](intrusion-indicators/linux-privesc.md)
- [Investigate unexpected local name resolution and authentication paths](intrusion-indicators/llmnr-nbtns-poisoning-relay.md)
- [Assess unexpected transit through an intermediate host](intrusion-indicators/port-redirection-tunneling.md)
- [Distinguish network exploration from expected fan-out](intrusion-indicators/recon-portscan-enum.md)
- [Identify assessment-like request patterns without assuming compromise](intrusion-indicators/vuln-scanning.md)
- [Review Windows execution trust paths and privileged outcomes](intrusion-indicators/windows-privesc.md)

### Malware

- [Evaluate memory loading as an evidence question](malware/reflective-loader/ATTACK.md)

### Memory And Platform

- [Assess macOS security decisions and unexpected execution](memory-and-platform/macos-control-bypass-residue.md)
- [Interpret crash and memory anomalies without inventing an exploit](memory-and-platform/memory-corruption-exploitation-residue.md)

### Web

- [Assess cross-origin access policy and observed disclosure](web/cors-cross-origin.md)
- [Verify object-level authorization with business context](web/idor.md)
- [Trace server-originated requests to their initiating context](web/ssrf.md)
- [Assess template processing with evidence of evaluation](web/ssti.md)
- [Investigate unexpected external resolution during XML processing](web/xxe.md)

### Web Advanced

- [Assess trust crossing in object reconstruction](web-advanced/insecure-deserialization.md)
- [Investigate unexpected shared-object state in JavaScript workloads](web-advanced/prototype-pollution.md)
- [Assess authentication decisions involving ambiguous input types](web-advanced/type-juggling-auth-bypass.md)
- [Verify that protected actions have the required authorization history](web-advanced/web-auth-bypass-logic.md)

## Experimental rule files

- [PE import inventory predicate](malware/reflective-loader/loader.yar) — statically selects a capability combination; no execution or family finding.
- [Registry and process-lineage predicates](malware/reflective-loader/behavior.yml) — two low-confidence Windows observations; no correlation or malware verdict.

## Concrete observation contract

The per-card observation sections are backed by four shared schema references:
[Windows](../skills/soc-detection-engineering/references/telemetry-windows.md),
[Linux/network](../skills/soc-detection-engineering/references/telemetry-linux-network.md),
[application/identity](../skills/soc-detection-engineering/references/telemetry-application-identity.md)
and [specialist sources](../skills/soc-detection-engineering/references/telemetry-specialist.md).
Choose the matching producer and deployed version. A listed artifact is a place to
request scoped evidence, not a promise that METIS parses it or that collection was enabled.

Keep one mapping row per required observation: raw provider/table/channel, event/action,
raw field and type, source path, collection policy/filter, entity key, normalized field,
time meaning, null handling and retained example locator. A completed query, a returned
HTTP status and a successful permission check each have narrower meanings than a
completed protected operation. Candidate rules remain unvalidated until those meanings
and their real backend behavior are tested on the recorded revision.
