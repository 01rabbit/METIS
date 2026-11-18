# Specialist evidence contracts

Use a platform-specific collector and schema. These locators help request evidence; METIS
does not supply radio coverage, an industrial parser, an Endpoint Security entitlement or
automatic parsing of every artifact named here. Collection changes and live response
still need the applicable authorization and resource allocation.

## macOS execution and privacy decisions

An Endpoint Security client can attach `es_process_t` metadata to a collected event.
`audit_token`, `parent_audit_token` and `responsible_audit_token` represent different
relationships; retain all available values rather than replacing them with one PID.
`signing_id`, `team_id`, `cdhash` and `codesigning_flags` support provenance assessment at
that observation time. Code-signing validity is neither an allow decision nor proof of
benign intent. Event availability, entitlement and OS version must be documented.

The `com.apple.quarantine` extended attribute and the user's candidate artifact at
`~/Library/Preferences/com.apple.LaunchServices.QuarantineEventsV2` are provenance leads
whose presence and private schema must be checked on the acquired OS version. Missing
quarantine state does not establish its removal or the file's origin. Common privacy
database locations are the user's `Library/Application Support/com.apple.TCC/TCC.db`
and `/Library/Application Support/com.apple.TCC/TCC.db`. These are sensitive, private
schemas, not a stable public API; inspect the acquired schema for the OS version before
interpreting a permission value. Preserve SQLite sidecar consistency. Do not weaken
privacy controls to obtain them. Unified-log activity from `tccd` and `syspolicyd` can
corroborate a decision but retention and redaction limit negative conclusions.

## Crashes and service failures

On Windows, Application Error 1000 and Windows Error Reporting 1001 in Application can
locate a process failure; Service Control Manager 7031/7034 in System concerns service
termination. Provider plus channel matters because the same event number is reused.
WER LocalDumps can place user-mode dumps in `%LOCALAPPDATA%\CrashDumps` by default when
configured; service accounts and custom `DumpFolder` settings change the location.
Relate exception code, faulting module, process lifetime and dump collection time. A crash,
fail-fast termination or mitigation event cannot alone establish exploit success. Treat
memory content as sensitive evidence and inspect acquired data without executing it.

## Industrial monitoring

For the current Zeek Modbus base schema, `modbus.log` includes connection `uid`, `ts`,
the `id` tuple, optional `func` and `exception`; optional `tid` and `unit` are transaction/unit
identifiers. Current `pdu_type` can distinguish request (`REQ`) from response (`RESP`),
but older schemas may omit these fields. Register address, quantity and
value are not universal columns in that base log; obtain them from an explicitly selected
passive parser and preserve its schema/version. Pair request and response with connection,
transaction and unit context. A normal protocol response is not proof of physical effect.
Controller/historian state, operator records and interlock context are separate evidence.
Do not send trial commands to determine whether a system accepts them.

## Wireless observation

Wireshark display fields can identify `wlan.fc.type_subtype`, `wlan.bssid`, `wlan.ssid`,
`wlan.sa`, `wlan.da` and `wlan.fixed.reason_code`. They describe captured frames, not
authenticated physical devices. Record adapter/channel coverage, time, frame loss and
Protected Management Frames context. Correlate WLAN controller associations and RADIUS
records: `Called-Station-Id` commonly represents AP/BSSID and SSID as specified for 802.1X,
whereas `Calling-Station-Id` identifies the supplicant station. Vendor event labels and
MAC-address randomization need local interpretation. Roaming, maintenance and RF faults
can produce disconnect bursts. Passive observations must not become a rationale for
transmitting deauthentication frames or active industrial traffic.

### Native Endpoint Security coordinates

An ES message's `event_type` selects the `event` union member. For
`ES_EVENT_TYPE_NOTIFY_EXEC`, distinguish the calling image in `process` from the new
image in `event.exec.target`. Their PID can be equal while their audit-token execution
identity differs. For either process structure, `executable` points to an `es_file_t`;
use its `path` with `path_truncated` and file metadata. A collector field spelled
`process.executable.path` is a serialization choice, not an interchangeable ECS contract.
`is_platform_binary` is a native Boolean describing Apple's platform signing category;
it does not authorize every action by that process.

For `ES_EVENT_TYPE_NOTIFY_DELETEEXTATTR`, the attribute name is in
`event.deleteextattr.extattr` and the affected file is `event.deleteextattr.target`.
`ES_EVENT_TYPE_NOTIFY_SETEXTATTR` uses `event.setextattr.extattr` and
`event.setextattr.target`; the event does not supply a universal new-attribute-value field.
An attribute-set record alone therefore cannot demonstrate that quarantine flags became
zero. For `ES_EVENT_TYPE_NOTIFY_MMAP`, inspect `event.mmap.source`, `file_pos`, `protection`
and `max_protection` in that member; mapping a file is not proof its instructions executed.
`ES_EVENT_TYPE_NOTIFY_CS_INVALIDATED` concerns the message's process, not an invented
`event.cs_invalidated.target` field. This notification is not an exhaustive sensor for
all signature failures or all prevented execution.

Bind these coordinates to the installed SDK, message `version` and collector transform.
The SDK's `EndpointSecurity/ESMessage.h` is a useful primary schema reference. Apple's
[execution event](https://developer.apple.com/documentation/endpointsecurity/es_event_exec_t),
[process metadata](https://developer.apple.com/documentation/endpointsecurity/es_process_t)
and [attribute deletion](https://developer.apple.com/documentation/endpointsecurity/es_event_deleteextattr_t)
document the native structures. Preserve notification versus authorization semantics;
do not infer allowed/completed activity from an authorization request alone.

### Privacy-store and unified-log candidates

For an acquired TCC database, inspect the actual `access` table definition first. Candidate
columns seen in modern layouts include `service` for the protected capability, `client`
for the application identity, `client_type` for its representation, `auth_value` for the
stored choice and `last_modified` for the record's clock value. These names are leads for
schema inspection, not a promised cross-version layout or a numeric permission decoder.
Keep the raw value/type, OS build and database scope; establish the timestamp unit and
numeric mapping for that build before conversion. This reference has no independently
verified universal mapping for those private columns. A stored choice is not proof that
the current application has effective access: policy, code identity and execution context
also matter. Apple's [TCC discussion](https://developer.apple.com/forums/thread/835851)
explains that limitation.

In a collected unified-log export, `subsystem`, `senderImagePath` and `eventMessage` are
useful coordinates when the selected output schema contains them. Subsystem values such
as `com.apple.TCC`, `com.apple.syspolicy` and `com.apple.securityd` are candidate filters;
a string mentioning AMFI is not itself a decision. Unified logging includes persistent
storage as well as live buffers; collection configuration, redaction and retention decide
what is recoverable. An unexpected TCC database writer or missing consent/quarantine
record needs process identity, authorized maintenance, policy and collection coverage
checks. Neither is a universal proof of control bypass.
