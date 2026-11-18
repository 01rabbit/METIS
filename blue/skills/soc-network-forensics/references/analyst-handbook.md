# Network evidence handbook

Use existing captures, broker exports and approved sensor telemetry. Preserve input hashes,
sensor location, capture filter, clock source, snap length, packet drops and tool versions.
Active probing, frame injection and controller changes are outside this handbook.

## Capture integrity and population

Identify format from bytes: pcap, pcapng, Linux cooked capture, logic-analyzer container and
raw interleaved I/Q need different parsers. Check interfaces, directions and missing packets.
Separate packets, flows, requests, sessions and actors before counting.

Reassemble both TCP directions, accounting for retransmission, overlap, out-of-order segments
and missing bytes. Preserve conflicts and gaps; never zero-fill and claim an authentic object.
Exported objects need stream offsets and digests. Consume declared binary body lengths rather
than interpreting command-like text inside a body. This matters for printer/PJL traffic.

Multiple sensors or NAT can duplicate transactions or change tuples. Deduplicate using a
documented identity, not timestamp alone. Transport addresses and asserted application headers
differ in trust. A SYN, failed handshake and application request are different observations.

## Flows, beaconing and exfiltration

Start with top talkers, identified services, connection states, duration and byte direction.
Ports alone do not identify protocols. Zeek orig/resp describes connection roles, not
internal/external; determine which endpoint owns each byte count.

Sort per entity by time before computing intervals. Record bin size, jitter, sample count,
window and gaps. Low variance also occurs in health checks, updates and monitoring. Add
destination rarity, host process and business baseline. Flow shape alone does not name malware.

Correlate outbound content volume with object access, process and destination. Backups,
downloads and replication are alternatives. Distinguish attempted from completed transfer;
encryption and truncation limit content claims.

## DNS

Group by client and a documented Public Suffix List-derived registered domain, including the
chosen private-suffix policy. Last-two-label grouping may combine unrelated tenants. Compare
unique names, label lengths, byte volume, types, responses and host process. TXT alone is not
suspicious; A-record channels exist, and benign security/CDN lookups can have high entropy.
NXDOMAIN bursts and successful bidirectional resolution are different phenomena.

Summary logs may omit response sections or unusual fields. Verify packet coverage before
claiming a field carries no data. Decode recorded labels offline, retaining original bytes
and transformations; do not issue fresh queries to the destination.

## HTTP, TLS and structured applications

Pair requests and responses in reassembled streams. Status alone does not prove authentication,
transfer or backend effect. Host headers, SNI and certificates have different trust and roles.
Observed virtual hosts do not authorize enumeration. TLS fingerprints are hints; encryption,
ECH and sensor placement limit visibility, and fingerprints do not identify an actor.

JSON-RPC IDs require exact type/value joins, including batches. Preserve unmatched and
ambiguous records. Cloud HTTP traces can contain catalogs, tenant IDs and token roles; tie
them to specific successful responses rather than assuming a URL implies authorization.
Preserve document content and personal information privately.

## MQTT

Use broker logs, configuration and captured CONNECT/SUBSCRIBE/PUBLISH exchanges. Record
client ID, authenticated principal, topic, QoS, retained state, session lifecycle and delivery.
TCP write, protocol acknowledgement and application consumption are different facts.
System-namespace topics have distinct wildcard matching rules; a broad subscription is not
proof of complete visibility.

Review ACL expansion for the deployed version and actual deny/allow policy. Identity
substitution, reconnects, duplicate IDs and retained messages alter the observed population.
Apparent cross-tenant delivery needs broker-side confirmation. Validate fixes with inert
messages in a separate authorized environment.

## Stateful and message-based transports

For Engine.IO/Socket.IO, preserve version, session ID, transport upgrade, namespace, heartbeat
deadline and reconnects. An expired session is not negative evidence about application data.
A polling response is not the same as successful event consumption.

For ZeroMQ, distinguish socket pattern, handshake, multipart framing, queue state and reply.
Successful send or kernel-buffer drain does not prove processing. Zero-byte read, timeout
and backpressure mean different things. Preserve complete short acknowledgements.

Silence can mean framing error, incomplete request, normal idle behavior, transport failure
or missing telemetry. Report the ambiguity. It does not authorize repeated probes.

## Industrial, building and vehicle networks

Prefer passive evidence for S7comm, OPC UA, BACnet and other control networks. Record source,
function/service, object/data-block identity, range, value, response and authorization.
Distinguish reads, writes and control operations. Polling intensity, batch size and latency
matter: intensive reading can interfere with operation.

Look for novel writers, changed write ranges, altered interlocks, controller state and
unexpected engineering stations. A read interface does not confer write authority. An IP or
reservation is not a cryptographic identity. Clean filesystem monitoring cannot establish
that process logic, firmware or actuator state is unchanged.

For bus proxies preserve device address, framing, byte order, status and error position.
A proxy error may not identify the failed downstream layer. SPI/JTAG reads can leave little
host telemetry; use physical access records and firmware digests. CAN identifiers describe
messages, not authenticated senders. Do not inject, replay, unlock or alter equipment.

## Radio, serial and space-link recordings

Check sample type, byte order, channel alignment, metadata boundaries, sample rate and burst
offset. Metadata can shift alignment. Compare differential channels where present. Constant
amplitude can still carry phase/frequency data; inspect phase differences and noise.

Derive timing independently. Short edge runs and transition noise bias minimum-run estimates.
A good preamble does not validate a payload. Short bursts may contain only one tone of a pair.
Fractional samples per symbol require windowed integration and explicit tail handling;
silently dropping a final symbol can invalidate the frame. Report timing uncertainty.

Validate documented frame boundaries, lengths, sync and checksum scope on complete recorded
frames; exclude degenerate constant-data coincidences. Checksums detect corruption but do not
authenticate origin. Retain malformed frames and diagnostics. A rejected decode describes
that decoder's limits, not automatically the signal.

Use residual analysis to distinguish carrier/quantization structure from modulation.
Floating-point phase accumulation can produce structured residuals. State noise floor and
sensitivity; correlation alone does not prove hidden content.

For CCSDS distinguish frame, packet, virtual channel, sequence and FECF. Do not substitute a
checksum for provenance. For scientific time telemetry record coordinate frame, epoch,
timescale, tolerances and rounding; rounding and truncation may display different seconds.

## Findings and completeness

Name sensor, artifact, stream/frame range, UTC time, interpretation, alternatives and missing
visibility. Independently replay consequential extractions. Parser success does not prove
complete capture or a target-side effect. Private transcripts and content stay outside Git.

## Field-level companion

The [packet and service-log map](packet-format-map.md) supplies native locations, field names,
count units and completeness checks for these investigations. Keep this handbook's reasoning
boundaries when applying those selectors. A parser can recognize HTTP, DNS or PJL while lacking
support for another protocol, link type, fragmentation mode or encrypted layer in the same capture;
a successful routing decision does not establish capture-wide completeness.

In particular, reject reassembly that silently inserts zero bytes into gaps or combines different
TCP lifetimes sharing one tuple. Do not treat a normal-looking decoded prefix as a complete object.
For an earliest-successful-request question, establish the application success condition before
sorting and retain all ties at the available timestamp precision.
