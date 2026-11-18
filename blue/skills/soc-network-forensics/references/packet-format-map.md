# Packet formats and service-log coordinates

Apply these selectors to preserved captures and approved log copies. Record parser version and
native field types. The table is a reading guide, not a live network scanner or a claim that METIS
ships implementations of every listed protocol.

## Capture containers and stream identity

| Location | Fields / structural facts | Correlation and units | Validation / limit |
| --- | --- | --- | --- |
| Classic pcap file header and packet records | 24-byte file header; magic identifies byte order and microsecond/nanosecond precision; packet header has seconds, fractional timestamp, captured length and original length | Packet time is Unix seconds since 1970-01-01 UTC plus fraction in the indicated unit; preserve link type and packet ordinal | Compare captured versus original size for every packet. Snap length alone does not prove which payloads were truncated. [libpcap format](https://raw.githubusercontent.com/the-tcpdump-group/libpcap/master/pcap-savefile.manfile.in) |
| pcapng Section/Interface/Enhanced Packet blocks | Section byte-order marker; interface ID, link type, snap length, `if_tsresol`, `if_tsoffset`; packet timestamp high/low and captured/original lengths | Interface numbering is section-local; resolution is decimal or binary exponent; offset is seconds | Validate leading/trailing block lengths and padding. Simple Packet Blocks lack timestamps; do not assign epoch zero as observed time. [pcapng format draft](https://www.ietf.org/archive/id/draft-ietf-opsawg-pcapng-04.html) |
| Packet analyzer frame and TCP fields | `frame.number`, `frame.time_epoch`, `frame.cap_len`, `frame.len`, `frame.interface_id`, `tcp.stream`, `tcp.seq`, `tcp.ack`, `tcp.len`, `tcp.flags` | Keep capture hash + frame number; stream indices are local to an analysis run | Tuple reuse, sequence wrap, retransmissions, missing segments and conflicting overlap need explicit handling. A new capture can renumber streams. [Frame fields](https://www.wireshark.org/docs/dfref/f/frame.html), [TCP fields](https://www.wireshark.org/docs/dfref/t/tcp.html) |
| Link and network layers | Ethernet/VLAN, raw IP, Linux cooked SLL/SLL2; `ip.src`, `ip.dst`, `ip.id`, fragmentation fields, IPv6 addresses | Confirm link-layer parser before resolving transport offsets; reassemble fragments using protocol-defined keys | An IPv4/UDP-only parser cannot claim to cover IPv6, fragmented DNS, TCP DNS or encrypted DNS. [Encapsulation identifiers](https://www.tcpdump.org/linktypes.html) |

For the cited pcapng draft v04, read each Enhanced Packet timestamp word using its
Section byte order, then combine the unsigned 32-bit high and low words into one
unsigned 64-bit tick count. Its clock belongs to the Interface Description Block
selected by the section-local interface ID. In the one-byte `if_tsresol`, bit 7 selects
binary rather than decimal resolution; the lower seven bits give the exponent.
One tick is 2 to the negative exponent seconds when that bit is set, otherwise 10
to the negative exponent seconds; an absent option means one microsecond.
`if_tsoffset` is a signed 64-bit seconds offset, defaulting to zero. Multiply ticks
by their unit and add this offset to obtain seconds since 1970-01-01 UTC; this offset
is not a display timezone. Keep raw words and exact tick units so floating-point
rendering cannot silently define the evidence's precision.
[Timestamp and interface options](https://www.ietf.org/archive/id/draft-ietf-opsawg-pcapng-04.html#section-4.3)

## Protocol records and success boundaries

| Location | Fields / structure | Correlation and measure | Validation / limit |
| --- | --- | --- | --- |
| Captured DNS messages | `dns.id`, `dns.flags.response`, `dns.flags.opcode`, `dns.flags.rcode`, `dns.qry.name`, `dns.qry.type`, `dns.count.queries`, `dns.count.answers`, `dns.count.auth_rr`, `dns.count.add_rr` | Pair transaction ID with endpoints, transport and time; count messages, questions and answers separately | Additional records may contain ordinary EDNS metadata. An authority record in a query requires protocol/context review, not an automatic tunneling verdict. [DNS analyzer fields](https://www.wireshark.org/docs/dfref/d/dns.html) |
| DNS name and RDATA boundaries | Header is 12 bytes; labels have a maximum 63-octet content; compression uses message-relative pointers; TXT RDATA can hold multiple length-prefixed strings | Preserve question/answer/authority/additional section and RR type for each extracted value; TTL is seconds | Bound pointer traversal, lengths and expansion. A decoded label is a hypothesis; verify its byte provenance, application meaning and host context. [DNS format](https://www.rfc-editor.org/info/rfc1035/) |
| HTTP/1 messages after TCP reassembly | `http.request.method`, `http.host`, `http.request.uri`, `http.user_agent`, `http.response.code`, `http.request_in`, `http.response_in`, `http.content_length` | Pair messages within one connection and order, including interim responses; record endpoint direction and message index | Transfer-Encoding, Content-Length, close-delimiting, HEAD and no-body status semantics govern body size. HTTP/2 and HTTP/3 require their own stream IDs. [HTTP analyzer](https://www.wireshark.org/docs/dfref/h/http.html), [HTTP/1 framing](https://www.rfc-editor.org/info/rfc9112/) |
| TLS handshake metadata | `tls.handshake.extensions_server_name`, TLS version/cipher fields and available certificate records | Relate handshake to capture/flow identity; name the fingerprint algorithm and input domain if used | Encrypted handshake portions, TLS 1.3 and ECH can hide fields. A self-signed certificate, uncommon port or fingerprint alone does not establish C2. [TLS analyzer fields](https://www.wireshark.org/docs/dfref/t/tls.html) |
| Recorded DHCP host claims | DHCP option 12 hostname, client hardware address/client identifier, assigned address, lease interval | Associate a name claim with the observed lease and time, then corroborate inventory or endpoint identity | A MAC or hostname can change or be asserted. Do not use list order as the most recent observation. [DHCP fields](https://www.wireshark.org/docs/dfref/d/dhcp.html) |
| Captured NTLM authentication metadata | `ntlmssp.messagetype` (unsigned 32-bit); authenticate strings `ntlmssp.auth.hostname`, `ntlmssp.auth.domain`, `ntlmssp.auth.username`; challenge strings `ntlmssp.challenge.target_name`, `ntlmssp.challenge.target_info.dns_computer_name`, `ntlmssp.challenge.target_info.nb_computer_name` | Keep packet/stream, endpoint direction and message type: authenticate fields assert client identity; challenge fields describe the peer target | Neither a hostname nor a username string establishes authentication success or a human identity. Retain the protocol result and host evidence separately. The listed NTLM selectors all exist in Wireshark 1.6.0–4.6.9; some appeared earlier. [NTLM fields](https://www.wireshark.org/docs/dfref/n/ntlmssp.html) |
| Captured DHCPv4 / name-service evidence | `dhcp.id`, `dhcp.hw.mac_addr`, `dhcp.option.hostname`, `dhcp.client_id.undef` (string) / `dhcp.client_id.uuid` (GUID) when present, `dhcp.ip.your`, `dhcp.option.dhcp_server_id`, `dhcp.option.ip_address_lease_time`; NBNS `nbns.name` | Relate client, server, transaction and ACK time; lease duration is seconds. Distinguish address offered from address acknowledged | A client-supplied name and hardware address are claims; relay/NAT, renewal and lease expiry change mappings. The two `dhcp.client_id` selectors are documented for Wireshark 3.0.0–4.6.9; older dissectors may use a `bootp` prefix. [DHCP fields](https://www.wireshark.org/docs/dfref/d/dhcp.html), [DHCP options](https://www.rfc-editor.org/rfc/rfc2132), [NBNS fields](https://www.wireshark.org/docs/dfref/n/nbns.html) |
| Archived raw-print/PJL stream | Line-delimited PJL records; observed `NAME`, `TYPE`, `SIZE`, `OFFSET`; job identifiers and device status where present | Bind each observation to direction, session, byte offset and frame; sizes/offsets are bytes | Consume a declared binary body before interpreting following text. A listing size is not measured transferred size. Port 9100 and embedded command-like text do not prove protocol boundaries or device-side completion. [PJL format manual](https://h10032.www1.hp.com/ctg/Manual/bpl13208.pdf) |
| Archived CCSDS Space Packet | Six-octet primary header: 3-bit version, 1-bit type, 1-bit secondary-header flag, 11-bit APID, 2-bit sequence flags, 14-bit sequence count/name, 16-bit length | Data bytes = stored length + 1; total packet bytes = 6 + data bytes. Sequence counting, when applicable, wraps at 16384 per APID | Check exact length and profile; secondary-header time format is mission-specific. Header recognition does not prove payload interpretation. [Space Packet specification](https://ccsds.org/Pubs/133x0b2e2.pdf) |
| Archived CCSDS TC frame under a declared profile | Five-octet primary header: version, bypass/control flags, reserved bits, spacecraft ID, virtual-channel ID, length and frame sequence; optional two-octet FECF | Frame length field encodes total octets minus one; identify spacecraft/virtual channel separately from packet APID | FECF presence and permitted frame types are managed parameters. Validate checksum scope and N/N+1 length cases; a CRC is not authentication or proof of executed control. [Historical TC format](https://ccsds.org/Pubs/232x0b2c1s.pdf); confirm the mission's standard edition |

## Web and authentication logs beside packet evidence

| Typical location | Fields to retain | Correlation / time | Validation / limit |
| --- | --- | --- | --- |
| Apache configured `CustomLog`, often `/var/log/apache2/access.log` or `/var/log/httpd/access_log` | Format tokens `%a`, `%h`, `%u`, `%t`, `%r`, `%>s`, `%b`, `%{Referer}i`, `%{User-Agent}i`; request ID if configured | Parse according to `LogFormat`; `%D` measures microseconds and `%T` seconds by default | Dash is not necessarily numeric zero. Address rewriting and proxy headers change attribution; a 2xx status is not proof of the requested backend effect. [Apache format](https://httpd.apache.org/docs/2.4/mod/mod_log_config.html) |
| NGINX configured `access_log`, commonly `/var/log/nginx/access.log` | `$remote_addr`, `$remote_user`, `$time_local`, `$request`, `$status`, `$body_bytes_sent`, `$http_referer`, `$http_user_agent`; optional `$request_time`, `$upstream_response_time`, `$request_id` | Use the configured `log_format`; request/upstream durations use seconds, potentially fractional | Multiple upstream attempts may produce several timing values; body bytes exclude response headers. Verify forwarding trust before using client headers. [NGINX access log](https://nginx.org/en/docs/http/ngx_http_log_module.html) |
| Linux auth files, commonly `/var/log/auth.log` or `/var/log/secure`, and persistent `/var/log/journal/` | Service/PID, account, authentication method, peer IP/port, accepted/failed/session-open/close; journal `__REALTIME_TIMESTAMP`, `_BOOT_ID`, `_PID`, `_SYSTEMD_UNIT`, `MESSAGE` | Journal realtime timestamps use Unix microseconds; qualify reused PID with boot/time; pair authentication with session evidence | Classic syslog may omit year/zone. Failed-password, invalid-user and PAM lines can describe one attempt; accepted authentication is not durable session use. [Journal fields](https://www.freedesktop.org/software/systemd/man/systemd.journal-fields.html) |

Compare asserted forwarding headers with the observed socket peer. For byte-volume claims, identify
the layer: captured frame bytes, IP bytes, transport payload and reconstructed application content
measure different things. Preserve unsupported, skipped and incomplete populations separately from
valid records that simply do not match the investigation predicate.

## Passive application and control-protocol coordinates

Inspect only already collected packets, logs and configuration snapshots. These selectors identify
observations; they do not authorize connecting to a broker, issuing controller requests or replaying frames.

| Evidence location | Native fields or record keys | Correlation / units | Validation / result limit |
| --- | --- | --- | --- |
| Captured MQTT session | `mqtt.ver`, `mqtt.msgtype`, `mqtt.clientid`, `mqtt.username`, `mqtt.topic`, `mqtt.msgid`, `mqtt.qos`, `mqtt.dupflag`, `mqtt.retain`, `mqtt.kalive` | Associate message ID with session and direction; keep-alive uses seconds. Retransmission and retained delivery affect counts | Client ID is not the authenticated principal. A protocol acknowledgement is not proof of consumer processing; validate visibility and QoS/version. [Dissector fields](https://www.wireshark.org/docs/dfref/m/mqtt.html) |
| Existing Mosquitto monitoring export | `$SYS/broker/publish/messages/received`, `/sent`, `/dropped`; current versions also expose `$SYS/broker/mqtt/publish/received` and peers | These cumulative PUBLISH counters reset with broker restart; keep observation time and broker identity | Delivered copies, accepted packets and unique payloads are different populations. Counter differences alone do not prove an ACL cause or complete subscriber visibility. [Broker counter definitions](https://mosquitto.org/man/mosquitto-8.html) |
| Recorded Engine.IO open packet and transport records | `sid`, `upgrades`, `pingInterval`, `pingTimeout`, `maxPayload`; preserve negotiated protocol version and transport | `sid` binds one session; heartbeat intervals are milliseconds and `maxPayload` is bytes | Reconnection changes the session. Transport success is separate from an application event or acknowledgement. [Engine.IO contract](https://socket.io/docs/v4/engine-io-protocol/) |
| Recorded ZMTP 3.x greeting and message frames | Version, mechanism, `as-server`, `Socket-Type`; frame `MORE`, length and command/message distinction | Keep connection and multipart boundaries; sum only complete frames in the intended message | Socket patterns and versions differ. A complete transport message does not prove a remote consumer acted on it. [ZMTP 3.0](https://rfc.zeromq.org/spec/23/) |
| Captured S7comm exchange | `s7comm.header.pduref` (unsigned 16-bit), `s7comm.header.rosctr` (unsigned 8-bit), `s7comm.param.func` (unsigned 8-bit), `s7comm.param.item.db` (unsigned 16-bit), `s7comm.param.item.area` (unsigned 8-bit), `s7comm.param.item.address.byte`, `s7comm.param.item.address.bit` (both unsigned 24-bit dissector fields), `s7comm.param.item.length` (unsigned 16-bit), `s7comm.param.item.transp_size`, `s7comm.data.returncode` (both unsigned 8-bit) | Bind request/response to the connection and PDU reference; retain item index, byte/bit address components and the transport-size-dependent length unit. These S7 selectors are documented for Wireshark 2.0.0–4.6.9 | A response status is not a historian measurement. Separate recorded read/write jobs from observed physical or process-state effects. [S7comm fields](https://www.wireshark.org/docs/dfref/s/s7comm.html) |
| Captured OPC UA binary service exchange | `opcua.RequestHandle`, `opcua.ServiceResult`, `opcua.StatusCode`, `opcua.Timestamp`; decoded node/service identity where visible | Match handles within channel/session context; distinguish service-wide status from per-operation results | Encrypted bodies may hide fields. A successful service result does not prove every returned item succeeded or that equipment changed state. [OPC UA fields](https://www.wireshark.org/docs/dfref/o/opcua.html) |

## Building-control and vehicle-bus recordings

Read these only from preserved captures or approved offline exports. Keep the capture hash,
frame or record coordinate, interface and observation time; they do not authorize device requests.

| Recorded format | Native coordinate and type | Correlation and limitation |
| --- | --- | --- |
| Wireshark BACnet APDU | `bacapp.type`, `bacapp.confirmed_service`, `bacapp.unconfirmed_service`, `bacapp.invoke_id` are unsigned 8-bit fields; `bacapp.objectType`, `bacapp.instance_number`, `bacapp.property_identifier` are unsigned 32-bit fields | Associate request/response by endpoint context, invoke ID, service and time; an invoke ID alone can repeat. Preserve segmented-message reconstruction and error/reject responses. Object type, instance and property identify different levels; an observed write is not proof of physical actuation. [BACnet display fields](https://www.wireshark.org/docs/dfref/b/bacapp.html) |
| Linux SocketCAN Classical CAN record | `struct can_frame`: 32-bit `can_id` contains identifier plus `CAN_EFF_FLAG`, `CAN_RTR_FLAG`, `CAN_ERR_FLAG`; `len` is an 8-bit payload length of 0–8 bytes, `data` contains the bytes | Separate 11-bit standard and 29-bit extended identifiers using the declared format. `can_dlc` is a deprecated alias for payload length; optional `len8_dlc` preserves raw DLC 9–15 only with an 8-byte payload and supporting configuration. [SocketCAN layout](https://www.kernel.org/doc/html/latest/networking/can.html) |
| Linux SocketCAN CAN FD record | `struct canfd_frame`: `can_id`, 8-bit `len` and `flags`, `data[64]`; payload length is 0–64 bytes | `CANFD_BRS` describes bit-rate switching and `CANFD_ESI` the transmitting controller's error state. Verify the container/frame format before interpreting flags or lengths. A CAN identifier describes a message/arbitration role and does not authenticate a transmitting node. [UAPI definitions](https://raw.githubusercontent.com/torvalds/linux/master/include/uapi/linux/can.h) |

BACnet property values require the acquired point configuration and change authority before
classifying them as abnormal. Device/network identity and point units remain separate from APDU
field names. SocketCAN structs do not themselves supply a universal capture timestamp; retain
and interpret the timestamp from the actual capture/export format. Do not infer sender identity
or physical behavior solely from an address, a message ID, a successful response or a checksum.

## SIP dialogs and RTP media from retained captures

Keep signaling events and media observations in separate timelines. A SIP dialog is scoped
by `Call-ID` and both endpoint tags. Retain `sip.Call-ID`, `sip.from.tag`, `sip.to.tag`,
`sip.CSeq.method`, `sip.CSeq.seq` and `sip.Status-Code` with frame/transport coordinates.
Forked dialogs, retries and a later INVITE inside an established dialog require separate
interpretation. `From`/`To` text asserts an identity; it does not verify the person speaking.
Report the endpoints of any duration calculation: initial request to termination, answered
dialog lifetime and observed media span answer different questions. Preserve fractional
capture time before applying a requested display or rounding rule.
[SIP dialog definitions](https://www.rfc-editor.org/info/rfc3261/) and
[SIP analyzer fields](https://www.wireshark.org/docs/dfref/s/sip.html) define these coordinates.

For each RTP direction, retain transport endpoints, negotiated media session, `rtp.ssrc`,
`rtp.seq`, `rtp.timestamp`, `rtp.p_type` and frame numbers. Sequence numbers are 16 bits;
timestamps and SSRC are 32 bits. RTP timestamps count media-clock ticks, not Unix seconds.
Use the negotiated codec/clock and RTCP time mapping where available. SSRC identity is scoped
to an RTP session; a relay can preserve it and a mixer can represent multiple contributors.
Do not concatenate media from different sessions merely because SSRC matches. Reconcile
loss, duplication, reordering, wrap and capture gaps before measuring content or duration.
[RTP semantics](https://www.rfc-editor.org/info/rfc3550/) and
[RTP analyzer fields](https://www.wireshark.org/docs/dfref/r/rtp.html) support this mapping.

Under the RTP audio/video profile, static payload type 0 identifies PCMU and 8 identifies
PCMA, both with an 8,000 Hz clock and one channel; dynamic mappings require the session
description. The former uses mu-law and the latter A-law with 8-bit encoded samples.
Decode only authorized captured media locally with a compatible bounded reader; preserve
frame provenance and codec metadata. Encrypted or missing media remains unexamined. A
speech transcript is derived evidence: retain audio intervals and verify consequential
words against the recording. [RTP payload profile](https://www.rfc-editor.org/info/rfc3551/).

## Passive Modbus response limits

For captured Modbus/TCP, preserve `mbtcp.trans_id` (uint16) and `mbtcp.unit_id`
(uint8) with endpoints, TCP connection and time; neither identifier is globally unique.
In Wireshark, `modbus.func_code` is uint8, `modbus.reference_num` is uint16, and
`modbus.bit_cnt` / `modbus.word_cnt` are uint16 counts of coils / registers, not byte
lengths. Field availability and decoding depend on version and message direction.
See the [Modbus fields](https://www.wireshark.org/docs/dfref/m/modbus.html) and
[TCP envelope fields](https://www.wireshark.org/docs/dfref/m/mbtcp.html).

A normal Write Multiple Coils (0x0F) or Write Multiple Registers (0x10) response carries
the starting address and quantity but omits the written values. Those values cannot be
recovered from that response alone: a matched request or independent state evidence is
needed. This differs from normal Write Single Coil (0x05) and Write Single Register
(0x06) responses, which echo the address and value. Separate normal and exception
responses. A protocol acknowledgement is not proof of subsequent physical behavior.
This distinction follows sections 6.5, 6.6, 6.11 and 6.12 of the
[application protocol](https://www.modbus.org/file/secure/modbusprotocolspecification.pdf).

## Client claims and server banners

For a supplied capture that exposes them, Wireshark's `rdp.userName`, `rdp.domain`
and `rdp.client.name` are character-string fields for client-supplied account/domain
and machine-name information. Bind them to the connection, frame and time. Repeated
client names do not authenticate a person or establish which accounts were targeted.
A Client Info record alone does not establish successful logon. Missing TLS does not
mean the Client Info data is readable: Standard RDP Security can also encrypt it.
The initial `mstshash` cookie is a separate optional connection-setup identifier;
keep its actual decoded schema rather than assuming it equals `rdp.userName`.
See [Wireshark RDP](https://www.wireshark.org/docs/dfref/r/rdp.html), Microsoft's
[Client Info security rules](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-rdpbcgr/86313d86-377e-4bab-97cb-c541dd9370ea)
and [connection request format](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-rdpbcgr/18a27ef9-6f9a-4501-b000-94b1fe3c2c10).

`http.server` is Wireshark's character-string selector for the HTTP Server header.
Treat its contents as a reported banner, not verified software identity. Response
status or length changes alone do not prove successful authentication. Likewise,
a MAC vendor prefix or a NetBIOS name is supporting context, not an operating-system
verdict. Preserve independent host evidence and the observed packet direction.
See the [HTTP field contract](https://www.wireshark.org/docs/dfref/h/http.html).

## Subscription scope and stream continuity

In preserved MQTT 3.1.1 traffic, a topic filter whose first character is `#` or `+`
does not match topic names beginning with `$`. A recorded `#` subscription therefore
omits the `$SYS` namespace; `$SYS/#` addresses that namespace but does not establish
coverage of every other `$` namespace. Interpret absence within the actual accepted
filters, session interval, authorization and capture coverage. This is a filter-matching
rule, not evidence that an unseen topic never existed. See
[MQTT 3.1.1 section 4.7.2](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html).

An observed RTP SSRC change or gap alone cannot establish a camera outage or its cause.
SSRC collision handling can change the identifier within a session; source restarts,
stream changes and capture loss also need separate evaluation. Correlate session/RTCP
metadata and independent device evidence before assigning an outage interval or cause.
See [RTP collision handling](https://www.rfc-editor.org/rfc/rfc3550.html#section-8.2).

Interpret Modbus application coordinates within a reassembled ADU, not at a universal
byte offset in each captured TCP packet. Segmentation and coalescing change packet-level
placement. Vendor-specific subfields require the matching vendor/version contract;
an undocumented offset or reply status remains unresolved rather than a standard field.

## Acquired Saleae capture and export boundaries

Identify the capture version before interpreting channel data. Saleae's published
[Logic 2 capture discussion](https://discuss.saleae.com/t/logic-2-capture-format-sal/1858)
describes a `.sal` ZIP container with `meta.json`, `digital-{channel}.bin` and
`analog-{channel}.bin` members. Treat these as discovery candidates in an acquired
container: record its hash, member identity and observed metadata rather than assuming
all software versions have the same internal layout. Channel number alone does not
identify a wire's function or an authenticated device.

The vendor distinguishes those internal members from documented binary exports and
states that the internal layout is unstable. Analog internal data also needs its
calibration context. An empirical varint rule, fixed offset or plausible decoded
waveform is insufficient to establish a reusable decoder. Prefer a compatible local
reader or an authorized offline export, preserving capture-to-export provenance;
confirm the export's own version, units, channel mapping and gaps. METIS has no validated
`.sal` internal decoder. See the [format boundary](https://new.saleae.com/support/logic-software/saving-and-exporting-data/sal-file-format).
Legacy `.logicdata` captures belong to Logic 1.x and are not directly compatible with
Logic 2; an extension rename does not convert them. See the [compatibility notice](https://new.saleae.com/support/logic-software/saving-and-exporting-data/open-logicdata-files).

## PJL file-operation errors in retained replies

A saved PJL file-operation response can contain `FILEERROR`, a decimal numeric status.
In the cited manual's file-system status family, value `n` corresponds to catalog status
`32000 + n`; this is not a general conversion for every PJL status. Match the acquired
reply to its operation, device/firmware, direction and stream byte/frame coordinates before
consulting that catalog. One failed operation establishes neither that the entire service
was unavailable nor that a different operation succeeded. Preserve the raw reply and
capture time; the status itself has no clock or transferred-byte count.
[PJL file-system response definition, printed page 9-6](https://h10032.www1.hp.com/ctg/Manual/bpl13208.pdf).

## Acquired Mosquitto persistence state

For Mosquitto v2.0.22, Boolean `persistence` defaults to `false`. When enabled,
`persistence_file` selects the filename, default `mosquitto.db`; `persistence_location`
selects the directory, otherwise the broker's current directory applies. Resolve the
acquired configuration and service context before assigning a path. A common package
layout is not a universal location.

The file preserves connection, subscription and message state for restart; normal
shutdown also saves it. It is not an append-only packet or delivery history. With `autosave_on_changes=false`,
`autosave_interval` is seconds, default 1800. With `true`, it is instead a threshold
for counted subscription changes, retained messages received and queued messages;
the documented save condition is that the count exceeds the threshold. Retain both
settings rather than converting the threshold unconditionally to a duration.

Saved disk state can lag memory; persistence being disabled or acquisition between
saves can explain missing state. Preserve acquisition time, configuration and file
hash separately from message/event clocks. Format versions can change, so require a
compatible bounded offline reader; `.db` alone does not establish SQLite. A missing
record does not prove that a topic never existed or a message was never delivered.
[Versioned persistence and autosave definitions](https://github.com/eclipse-mosquitto/mosquitto/blob/v2.0.22/man/mosquitto.conf.5.xml).
