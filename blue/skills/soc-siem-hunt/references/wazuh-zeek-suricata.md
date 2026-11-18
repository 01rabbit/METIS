# Host alerts and network sensor evidence

## Wazuh

Compare alert output with available raw/archive records and agent health. An event may arrive
without a useful decoder or matching rule. Agent disconnection, decoder failure and no
matching behavior are different explanations for silence.

Treat rule ID and level as deployment-specific metadata, not proof of attack. Record the
ruleset revision, decoder fields, agent identity and raw event. File-integrity records can
provide path, action and before/after values; the event still needs change-management context.
Do not assume raw archiving is enabled.

## Zeek

Select logs by protocol and collection configuration. Connections provide transport roles,
duration, state and directional volume; protocol logs add application observations. TLS
fingerprints, certificate checks and file hashes can require scripts/packages or configuration.

Connection UID joins many connection/protocol records, but not every log shares one key.
File analysis uses file identifiers and connection associations; inspect the schema rather
than joining everything on a nonexistent uid column.

Interpret orig/resp as observed connection roles. Missing handshake packets and asymmetric
capture alter connection state. A sequence of unanswered attempts can reflect filtering or
failed services as well as scanning; corroborate breadth and context.

For beaconing, order records within each tuple before computing gaps and evaluate count,
variance and benign scheduled activity. For DNS, use the correct registered-domain grouping
and response/host context. Naive suffix splitting can merge unrelated customers of a shared
provider. A rare TLS fingerprint is enrichment, not attribution.

## Suricata

Use EVE event_type to distinguish alerts, flows, application records and file information.
Relate records with the available flow/transaction identifiers and capture context. Do not
treat alert count as unique session or exploit count. Signature revision, action and sensor
mode determine whether the sensor merely alerted or actually blocked anything.

Inspect protocol detection, encrypted visibility, packet loss and stream-reassembly gaps.
File hashes depend on actual hashing configuration and bytes seen; a truncated object cannot
be assigned the digest of its complete presumed file.

## Joint analysis

Align clocks, tuple direction, sensor vantage point and deduplication rules before combining
host alerts with network evidence. A signature match establishes its predicate, not all
downstream effects. Host process and identity telemetry help distinguish an attempted request
from execution or data access. Retain supporting records and explicit coverage limitations.

## Wazuh: storage and field coordinates

| Default location / record | Fields to inspect | Correlation / measurement | Validation / limit |
| --- | --- | --- | --- |
| Manager `/var/ossec/logs/alerts/alerts.json`; optional `/var/ossec/logs/archives/archives.json` | `timestamp`, `id`, `agent.id`, `agent.name`, `agent.ip`, `manager.name`, `location`, `full_log` | Keep manager and agent context with alert ID; archive records and alert records are separate populations | Archive JSON requires `logall_json`; an absent archive is not evidence of absent incoming activity. [Event storage](https://documentation.wazuh.com/current/user-manual/manager/event-logging.html) |
| Decoded alert | `rule.id`, `rule.level`, `rule.groups`, `rule.mitre.id`, `decoder.name`, `data.*` | Relate the alert to its raw message and exact ruleset version | Decoder-dependent fields such as `data.srcip` or `data.dstuser` are not universal. Rule IDs/levels indicate a rule result, not proven compromise. [Alert structure](https://documentation.wazuh.com/current/user-manual/ruleset/index.html) |
| Windows Event Channel alert | `data.win.system.eventID`, `.providerName`, `.channel`, `.computer`, `.eventRecordID`, `.systemTime`; `data.win.eventdata.*` | Retain agent + channel/provider + record ID and log lifetime; `systemTime` is the source clock, separate from alert `timestamp` | Wazuh field names differ from `winlog.event_id` and `winlog.event_data.*`; preserve the observed casing and types. Decoder rules may refer to `win.*` without the outer alert `data` envelope. [Windows collection](https://documentation.wazuh.com/current/user-manual/capabilities/log-data-collection/configuration.html), [JSON alert example](https://documentation.wazuh.com/current/user-manual/manager/event-logging.html) |
| File-integrity alert | `syscheck.path`, `syscheck.event`, `syscheck.mode`, `syscheck.size_before`, `.size_after`, `.sha256_before`, `.sha256_after`, `.mtime_before`, `.mtime_after`, `.audit` | Pair before/after fields for the same agent and path; preserve the native values and the changed-attribute list | Added/deleted objects may lack one side. Who-data attribution requires supporting audit collection. A content change is not execution. [FIM fields](https://documentation.wazuh.com/current/user-manual/capabilities/file-integrity/advanced-settings.html) |
| Rules/configuration evidence | `/var/ossec/etc/ossec.conf`, `/var/ossec/etc/rules/`, `/var/ossec/etc/decoders/`, packaged `/var/ossec/ruleset/` | Record the effective decoder/rule and collection configuration used during the interval | Read approved snapshots; changing rules, enabling archives or restarting services is a separate write action. [Ruleset locations](https://documentation.wazuh.com/current/user-manual/ruleset/custom.html) |

## Zeek: select the right association key

Log directories are configured by the deployment. First read TSV headers `#separator`, `#fields`,
`#types`, `#unset_field`, `#empty_field`, or the actual JSON schema. Do not hard-code tabs or turn an
unset value into zero. [ASCII log format](https://docs.zeek.org/en/current/log-formats.html)

| File | Fields | Correlation / units | Validation / limit |
| --- | --- | --- | --- |
| `conn.log` | `ts`, `uid`, `id.orig_h`, `id.orig_p`, `id.resp_h`, `id.resp_p`, `proto`, `service`, `conn_state`, `history`, `duration`, `orig_bytes`, `resp_bytes`, `orig_pkts`, `resp_pkts`, `missed_bytes` | `ts` uses Unix seconds, `duration` seconds; join protocol logs on sensor + `uid` | Payload bytes differ from IP bytes; originator/responder are connection roles. Missing handshake or asymmetric traffic limits state interpretation. [Connection schema](https://docs.zeek.org/en/current/scripts/base/protocols/conn/main.zeek.html) |
| `dns.log` | `uid`, `trans_id`, `query`, `qtype`, `rcode`, `answers`, `TTLs`, `rejected` | Retain query time, connection and DNS transaction; TTLs are seconds | IDs can repeat; retransmissions and multiple questions/answers complicate counts. Summary fields do not preserve every DNS section. [DNS schema](https://docs.zeek.org/en/current/scripts/base/protocols/dns/main.zeek.html) |
| `http.log` | `uid`, `trans_depth`, `method`, `host`, `uri`, `status_code`, `request_body_len`, `response_body_len`, `orig_fuids`, `resp_fuids` | Use transaction depth within the connection; file associations refer to `files.log.fuid` | Multiple messages can share one connection. Logged body length is not automatically a complete exported object. [HTTP schema](https://docs.zeek.org/en/current/scripts/base/protocols/http/main.zeek.html) |
| `files.log`, Zeek 9.0.0 | `fuid` is a string; optional `uid` is a connection string and optional `id` has type `conn_id`. Retain `source`, `mime_type`, `filename`, `seen_bytes`, `total_bytes`, `missing_bytes`, `overflow_bytes` and configured hashes | Join the row's `uid` to connection/protocol records within the same sensor/run. `fuid` identifies the file observation, not a connection | A file associated with several connections produces several rows sharing its `fuid`. File-level byte counters can repeat across those rows; do not sum them as independent transfers. A file without network context can lack `uid`/`id`. [Versioned file schema and writer](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/scripts/base/frameworks/files/main.zeek) |
| `files.log`, legacy Zeek 5.0.0 | `conn_uids` is `set[string]`; `tx_hosts` and `rx_hosts` are `set[addr]`, alongside string `fuid` | Expand the connection set only when that acquired schema contains it; preserve one file's association with several connections | The writer documents the change to individual connection rows in 5.1. Confirm the actual `#fields`/`#types` or JSON schema before choosing either layout. Do not rename a set into a scalar `uid`. [Legacy schema](https://raw.githubusercontent.com/zeek/zeek/v5.0.0/scripts/base/frameworks/files/main.zeek) |
| `ssl.log` and `x509.log` | TLS `uid`, `server_name`, `version`, `cipher`; current `cert_chain_fps` to X.509 `fingerprint` | Match certificate fingerprints with the selected hash algorithm; retain connection link | Older logs may instead expose `cert_chain_fuids` and X.509 `id`; inspect the installed schema. Certificate availability depends on protocol visibility. [TLS certificate fields](https://docs.zeek.org/en/current/scripts/base/protocols/ssl/files.zeek.html), [X.509 schema](https://docs.zeek.org/en/current/scripts/base/files/x509/main.zeek.html) |

## Suricata EVE: event type before field selection

| Default location / event | Fields | Correlation / measure | Validation / limit |
| --- | --- | --- | --- |
| Configured EVE JSON output, commonly `/var/log/suricata/eve.json` | `timestamp`, `event_type`, `flow_id`, `src_ip`, `src_port`, `dest_ip`, `dest_port`, `proto`, `app_proto` | Join with sensor/run context + `flow_id`; `tx_id` identifies an application transaction where present | A flow can produce many EVE events. `community_id` needs compatible configuration for cross-sensor joins. [EVE format](https://docs.suricata.io/en/latest/output/eve/eve-json-format.html) |
| `event_type=alert` | `alert.signature_id`, `alert.rev`, `alert.signature`, `alert.category`, `alert.severity`, `alert.action` | Count signature observations separately from flows and transactions | Action and inline mode matter; an alert alone does not establish successful impact or prevention. [EVE format](https://docs.suricata.io/en/latest/output/eve/eve-json-format.html) |
| `event_type=fileinfo` | `fileinfo.filename`, `fileinfo.size`, `fileinfo.state`, `fileinfo.stored`, `fileinfo.gaps`, optional `fileinfo.sha256` | Relate file observation to flow/transaction and content range, if present | `CLOSED`, `TRUNCATED` and missing ranges are different states; an absent hash is not a match failure. [EVE format](https://docs.suricata.io/en/latest/output/eve/eve-json-format.html) |
| `http`, `dns`, `tls` EVE events | HTTP `hostname`, `url`, `http_method`, `status`; DNS `rrname`/query-answer arrays by format version; TLS `sni`, `version`, certificate fields where visible | Select the event-specific object and verify logger/schema version before flattening | TLS fingerprints are optional; a DNS schema upgrade can change arrays and cardinality. [EVE output configuration](https://docs.suricata.io/en/latest/output/eve/eve-json-output.html) |

## Native values needed for protocol and coverage pivots

For Zeek `conn_state`, `S0` records an attempt without an observed response, `REJ` a rejected
attempt, `S1` establishment without termination, and `SF` normal establishment/termination.
`RSTO` and `RSTR` distinguish the side sending a reset; `OTH` means no SYN was observed.
These are observation summaries. Filtering, packet loss and starting a capture midstream can
produce the same state as other causes, so a state value alone cannot establish scanning or
successful application use. [Connection states](https://docs.zeek.org/en/current/scripts/base/protocols/conn/main.zeek.html).

Suricata EVE HTTP metadata includes `http.http_user_agent`, `http.http_content_type` and,
when emitted, `http.http_refer`. TLS metadata can include `tls.subject`, `tls.issuerdn`,
`tls.notbefore`, `tls.notafter`, `tls.ja3.hash`, `tls.ja3.string`, `tls.ja3s.hash` and
`tls.ja3s.string`. Keep fingerprint input strings distinct from their hashes and retain
logger settings/version; optional TLS fingerprints and extended headers require collection
support. Certificate dates concern validity, not connection occurrence.
[EVE protocol fields](https://docs.suricata.io/en/latest/output/eve/eve-json-format.html).

For collection health, inspect configured `stats.log` or EVE `event_type=stats` records.
Counters include `capture.kernel_drops` and `tcp.reassembly_gap`; EVE can nest them beneath
`stats`, with totals and per-thread records controlled by configuration. Establish reset
boundaries, sensor identity and counter scope before comparing samples. A missing counter
is not zero and a zero drop count cannot prove that every unmonitored path was visible.
[Statistics output configuration](https://docs.suricata.io/en/latest/output/eve/eve-json-output.html),
[counter registration](https://raw.githubusercontent.com/OISF/suricata/main/src/stream-tcp.c),
[pcap collection counters](https://raw.githubusercontent.com/OISF/suricata/main/src/source-pcap.c).

## Optional TLS fields and HTTP byte counts

For Zeek 9.0, confirm the loaded policy scripts and observed log schema:

| Native log field | Type and meaning | Interpretation limit |
|---|---|---|
| `ssl.log` `curve` | Optional string naming the ECDH/ECDHE curve selected by the server | An empty/missing value alone does not establish explicit curve parameters, weak cryptography or failed negotiation |
| `ssl.log` `validation_status` | Optional string added by `policy/protocols/ssl/validate-certs.zeek`; certificate-chain validation result | Retain the sensor's trust material and validation context. Missing policy/output is not a successful validation, and an error is not automatically a self-signed certificate |
| `x509.log` `certificate.key_length` | Optional `count`, in bits; interpret with `certificate.key_alg` and optional `certificate.key_type` | Key bit length is not a cross-algorithm security-strength value; retain the existing fingerprint/connection mapping |

These contracts follow the [TLS schema](https://docs.zeek.org/en/current/scripts/base/protocols/ssl/main.zeek.html),
[validation policy](https://docs.zeek.org/en/current/scripts/policy/protocols/ssl/validate-certs.zeek.html)
and [versioned certificate type](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/scripts/base/init-bare.zeek).

The native HTTP fields `request_body_len` and `response_body_len` are `count` values
for uncompressed body content in bytes, from client and server respectively. They are
not a count of complete exported objects or TCP wire bytes. Keep `uid`/`trans_depth`
and capture completeness with the measurement; a shortened collector alias needs an
explicit mapping. [HTTP record contract](https://docs.zeek.org/en/current/scripts/base/protocols/http/main.zeek.html).


## Additional retained network-log coordinates

These are Zeek 9.0.0 file-output stream names. Resolve the actual directory, writer,
loaded analyzers/policies, filters and rotation from the acquired deployment. The
base `Log::default_logdir` is empty, meaning the working directory; a managed
installation can select another directory. A missing file does not establish no
matching traffic. [Versioned logging contract](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/scripts/base/frameworks/logging/main.zeek).

The protocol rows below retain `ts` (`time`), `uid` (`string`) and `id` (`conn_id`).
For notice/weird records the connection fields are optional. Scope connection joins
to the same sensor/run, and retain the log hash and record coordinate: a connection
can contain several protocol observations. Preserve the actual writer's clock
representation and unset values; a Zeek `interval` is a duration in seconds.

| Retained log | Native selectors in this version | Interpretation and join boundary |
| --- | --- | --- |
| `notice.log` | `note` (`Notice::Type`); optional string `msg`, `uid`, `fuid`; `actions` (`Notice::ActionSet`); `suppress_for` (`interval`) | A policy-generated notice can concern a connection or file; use its available UID/FUID relation. Notice actions and suppression affect the population. A notice is not proof of compromise. [Schema](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/scripts/base/frameworks/notice/main.zeek) |
| `weird.log` | `name` (`string`); optional strings `addl`, `source`; `notice` (`bool`); optional `uid` | Describes an analyzer's unusual observation; `notice` says it was also turned into a notice. Capture loss, implementation differences and malformed benign traffic remain alternatives. A weird alone proves neither tunneling nor evasion. [Schema](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/scripts/base/frameworks/notice/weird.zeek) |
| `ssh.log` | Optional strings `client`, `server`; optional `auth_success` (`bool`); `auth_attempts` (`count`) | Authentication inference uses packet-size observations and can be unavailable, including with compression. Attempts are not all failures. Retain host authentication evidence before attributing a human or session outcome. [Schema and inference](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/scripts/base/protocols/ssh/main.zeek) |
| `smtp.log` | `trans_depth` (`count`); optional `mailfrom`, `msg_id`, `date` (`string`); optional `rcptto` (`set[string]`); `tls` (`bool`) | Use UID plus transaction depth for messages on one connection. Envelope sender/recipients differ from message headers; `date` is header text, not the sensor clock. A visible transfer does not prove mailbox delivery or user access. [Schema](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/scripts/base/protocols/smtp/main.zeek) |
| `smb_files.log` | Optional `fuid`, `path`, `name`, `prev_name` (`string`); optional `action` (`SMB::Action`) | `SMB::logged_file_actions` filters retained actions. Keep the connection UID separate from the file FUID; when present, the latter relates to `files.log`. Path/name observations and rename metadata do not prove completed transfer or execution. [FileInfo and stream](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/scripts/base/protocols/smb/main.zeek) |
| `dce_rpc.log` | Optional `named_pipe`, `endpoint`, `operation` (`string`); optional `rtt` (`interval`) | `endpoint` is a name resolved from a UUID. RTT needs both request and response; an absent duration is not zero. Keep each operation's record/time within the connection, without claiming its downstream effect. [Schema](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/scripts/base/protocols/dce-rpc/main.zeek) |
| `kerberos.log` | Optional `request_type`, `client`, `service`, `error_msg` (`string`); optional `success` (`bool`), `from`/`till` (`time`) | Separate AS/TGS/AP request roles and ticket-validity times from observation time. A result or ticket does not alone establish later service use or a human identity; missing success is unknown. [Schema](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/scripts/base/protocols/krb/main.zeek) |
| `ntlm.log` | Optional `username`, `hostname`, `domainname`, `server_nb_computer_name`, `server_dns_computer_name`, `server_tree_name` (`string`); optional `success` (`bool`) | Client-supplied identity labels and server challenge names have separate roles. Correlate the connection with host authentication records; an observed name is not proof of its owner or a completed login. [Schema](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/scripts/base/protocols/ntlm/main.zeek) |

For Suricata 8.0.0, inspect acquired `outputs` → `fast` settings: `enabled`,
`filename` and `append`, together with `default-log-dir` and any command-line
log-directory override. The default basename is `fast.log`; a common resolved
location is `/var/log/suricata/fast.log`, not a universal path.
[Versioned output configuration](https://raw.githubusercontent.com/OISF/suricata/suricata-8.0.0/suricata.yaml.in).

The ordinary IP-alert line renders a timestamp, generator/signature/revision triple,
message, classification, priority, protocol and endpoints. ICMP endpoint suffixes
represent type/code rather than TCP/UDP ports; decoder-event lines can instead
contain a raw-packet summary. Preserve file hash and line/byte coordinates. This
text format is not EVE JSON and does not supply its `flow_id`/`tx_id` join fields;
time/tuple/signature correlation remains a candidate relation until corroborated.
The timestamp renders sensor-local calendar time with microsecond precision and
no numeric zone suffix; retain the sensor timezone instead of assuming UTC.
Neither line count nor a signature match establishes successful impact.
[Fast writer](https://raw.githubusercontent.com/OISF/suricata/suricata-8.0.0/src/alert-fastlog.c)
and [time rendering](https://raw.githubusercontent.com/OISF/suricata/suricata-8.0.0/src/util-time.c).


## Directory, address-allocation and industrial log contracts

Use the acquired deployment's stream definitions and writer schema. The following core
rows are fixed to Zeek 9.0.0; the industrial extensions below have separate revision pins.
These are external sensor contracts, not additional METIS decoders. Preserve unset values,
record coordinates, sensor/run identity and capture gaps before deriving an absence.

| Core log | Native fields and types | Association and observation limit |
| --- | --- | --- |
| `ldap.log` | `ts` (`time`), `uid` (`string`), `id` (`conn_id`); optional `message_id` and `version` (`int`), `opcode`, `result`, `diagnostic_message`, `object`, `argument` (`string`) | Non-search operations are grouped by connection and message ID. Keep that operation boundary and interval; a connection UID alone can join several operations. A result describes the recorded LDAP operation, not later resource use. |
| `ldap_search.log` | `ts`, `uid`, `id` have the preceding types; optional `message_id` (`int`), `scope`, `deref_aliases`, `base_object`, `filter`, `result` (`string`), `result_count` (`count`) | Bind the search to UID and message ID within the sensor/run and interval. `result_count` increments for observed search-result entries; it is not a distinct-person count or proof of a complete directory export. Encrypted traffic and incomplete analyzer coverage can hide search details. A broad filter alone does not identify an operator or tool. |
| `dhcp.log` | `ts` (`time`), `uids` (`set[string]`), `msg_types` (`vector of string`), `duration` (`interval`); optional `client_addr`, `server_addr`, `requested_addr`, `assigned_addr` (`addr`), `mac`, `host_name`, `client_fqdn`, `domain` (`string`), `lease_time` (`interval`) | This DHCPv4 conversation aggregates messages around a transaction within configured bounds. Expand `uids` to connection records; do not invent a scalar `uid` or an exported transaction-ID column. `ts` is the earliest observed message time; duration and lease interval are seconds. Requested, assigned and observed client addresses differ. Names/MACs need inventory corroboration, and this schema does not establish DHCPv6 Advertise/Reply visibility. |
| `dnp3.log` | `ts` (`time`), `uid` (`string`), `id` (`conn_id`); optional `fc_request`, `fc_reply` (`string`) and `iin` (`count`) | The basic request/reply log is distinct from an extension's object/control detail. This writer sets `ts` from `network_time()` in both request and response handlers; a reply row's time is not necessarily the request time despite the field comment. Join within the connection and observed interval; a protocol response is not physical-effect evidence. |

Definitions: [LDAP records and writers](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/scripts/base/protocols/ldap/main.zeek),
[DHCP conversation schema](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/scripts/base/protocols/dhcp/main.zeek),
[DHCPv4 wire layout](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/src/analyzer/protocol/dhcp/dhcp-protocol.pac)
and [DNP3 writer](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/scripts/base/protocols/dnp3/main.zeek).

The extension rows are passive observations from installed ICSNPP packages, whose log
layouts are not the core Zeek protocol schema. Confirm the actual package revision and
loaded scripts. Their records retain `ts` (`time`), `uid` (`string`) and `id` (`conn_id`);
join UID to the same sensor/run's connection. Preserve the writer's time representation
and any source/destination or `is_orig` fields; connection roles are not device ownership.
A recorded request, status or transferred block is distinct from approved change authority,
controller execution and a measured physical effect. Use retained evidence only.

| Log and pinned producer | Native selectors | Interpretation and join boundary |
| --- | --- | --- |
| `bacnet.log`, ICSNPP BACnet at `804ecefa23f65de59cd4f955738361c45795724f` | `bvlc_function`, `pdu_type`, `pdu_service`, `result_code` (`string`); `invoke_id` (`count`); `is_orig` (`bool`) | This is header-level evidence. For property observations use the companion `bacnet_property.log`: `object_type`, `property`, `pdu_service`, `value` are strings; `instance_number`, `array_index`, `invoke_id` are counts. Do not substitute presumed `service_choice` or `property_id` columns. Relate request/response with connection, direction, invoke ID, service and time; an invoke ID can repeat and values can be unset. [Record declarations and streams](https://raw.githubusercontent.com/cisagov/icsnpp-bacnet/804ecefa23f65de59cd4f955738361c45795724f/scripts/icsnpp/bacnet/main.zeek) |
| `dnp3_control.log`, ICSNPP DNP3 at `b31dbadeceb1cbcda16aef89c650559cd177dd7e` | Optional `is_orig` (`bool`), `block_type`, `function_code`, `operation_type`, `status_code` (`string`), `index_number` (`count`) | These are parsed control-block observations. The writer retains status for responses and removes it from requests. Keep the connection, object index, direction and interval together; neither a missing status nor an operation label proves completion. [Control schema and writer](https://raw.githubusercontent.com/cisagov/icsnpp-dnp3/b31dbadeceb1cbcda16aef89c650559cd177dd7e/scripts/main.zeek) |
| `modbus_detailed.log`, ICSNPP Modbus `v2.0.0` | Optional `tid`, `unit`, `address`, `quantity` (`count`); `func`, `exception_code`, `modbus_detailed_link_id` (`string`); `request_values`, `response_values` (`vector of count`); `matched` (`bool`) | `unit` is the native log column, distinct from connection `uid`; do not rename it to a presumed `unit_id`. Verify address/quantity meaning against the recorded function. `matched` describes the parser's pairing decision, not an independent same-flow guarantee: corroborate connection, transaction, unit and time. The link ID relates extension detail records when populated. [Versioned schema and pairing](https://raw.githubusercontent.com/cisagov/icsnpp-modbus/v2.0.0/scripts/main.zeek) |
| Same filename, ICSNPP Modbus `v1.0.0` | Optional `values` and `request_response` (`string`), plus `tid`, `unit`, `address`, `quantity` (`count`) and `func` (`string`) | This earlier layout uses a single string value field, not the version 2 request/response vectors. Keep the original schema; a filename alone cannot select either contract or a unit conversion. [Earlier declaration](https://raw.githubusercontent.com/cisagov/icsnpp-modbus/v1.0.0/scripts/main.zeek) |
| `s7comm.log`, ICSNPP S7comm at `7ebeb03a0f954541369361651d1c27d09a64b5a3` | `rosctr_code`, `pdu_reference` (`count`); `rosctr_name`, `function_code`, `function_name`, `error_class`, `error_code` (`string`); `is_orig` (`bool`) | The general log renders `function_code` as hexadecimal text, not a count. Keep UID, direction, PDU reference and time for request/reply association; a repeated PDU reference is not a global transaction ID. [General declaration and writer](https://raw.githubusercontent.com/cisagov/icsnpp-s7comm/7ebeb03a0f954541369361651d1c27d09a64b5a3/scripts/icsnpp/s7comm/main.zeek) |
| `s7comm_upload_download.log`, same pinned S7comm producer | `pdu_reference`, `session_id`, `blocklength` (`count`); `rosctr`, `function_name`, `function_status`, `filename`, `block_type`, `block_number`, `destination_filesystem` (`string`); `is_orig` (`bool`) | This transfer-detail record does not declare `function_code`; use its native function name and relate it to the general row only with connection, PDU/direction and time evidence. Preserve `block_number` as text. A transfer-stage observation or filename is not proof of a complete installed program or its execution. |

A label such as `smb.log` remains an unresolved exporter/legacy/custom-stream lead until
its producer and schema are identified. The Zeek 9.0.0 base SMB module instead creates
`smb_files` and `smb_mapping` streams. Use the `smb_files.log` contract above for file
observations when that is the actual stream; do not silently assign its fields to an
unknown `smb.log` artifact. [Pinned SMB streams](https://raw.githubusercontent.com/zeek/zeek/v9.0.0/scripts/base/protocols/smb/main.zeek).
