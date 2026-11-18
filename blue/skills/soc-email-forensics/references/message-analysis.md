# Message and mailbox evidence

## Acquisition and interpretation

Preserve the original message bytes and hash before parsing. Record whether the input is a
single message, a mailbox, header-only export or provider event stream. MSG/PST/OST require
a suitable parser/exporter; treating binary containers as text is not complete analysis.
For mailbox deduplication, compare transport IDs, message digest, recipient and delivery
context. Message-ID is not globally trustworthy and one message can have several deliveries.

Locate the first receiving hop controlled by the organization. Evaluate subsequent trusted
Received and Authentication-Results records using that boundary; earlier headers can be
sender-supplied. A claimed receiver hostname or authserv-id does not establish that trust: verify
its origin using the provider trace and the organization's header removal/generation policy.
Without that independent boundary evidence, label the authentication assertions unverified.
Distinguish envelope sender, visible From, Reply-To and authenticated domain.
SPF concerns a sending host and envelope identity; DKIM validation concerns signed content
and signing domain; DMARC adds alignment to the visible From domain. Forwarding and mailing
lists can complicate the result. A passing result does not establish a benign message.

Preserve raw Date and trusted receipt times separately. Timezone conversion must not turn a
sender-controlled Date into proof of transport chronology. Relays, retries and quarantine
release can explain different delivery times.

## MIME, links and attachments

Inventory MIME parts with their declared type, detected format, transfer encoding, size and
disposition. Decode onto bounded private copies. Restrict nested archive expansion and
aggregate extracted size. Duplicate or malformed MIME boundaries create a coverage issue.
Inline CID resources and attached messages are not ordinary standalone attachments.

Compare a link's displayed label, literal destination and any observed redirection chain.
Decode the representation without visiting the destination. A security product's URL wrapper
is a separate layer; keep both representations. Do not render active HTML, fetch tracking
images or upload attachments while examining the message.

Hash each extracted attachment and preserve its parent-part coordinate. Route macros,
scripts, links, disk images and nested documents to static triage. Filename extension is only
a hint. Do not execute an attachment to determine its type.

## Delivery, action and conclusions

Join provider trace/quarantine records by stable message and recipient coordinates. A sent
message, accepted SMTP transaction, mailbox delivery, opened message and clicked link are
different observations. Link scanning by security infrastructure can create click records.
Require user/device context before attributing a click to a person.

A delivery-and-click finding still needs endpoint or identity evidence to claim compromise.
Correlate attachment processing, process creation, downloaded content and subsequent login
activity. State whether mail security, endpoint and sign-in coverage cover the required window.

Useful output has one disposition (benign explained, suspicious, confirmed malicious delivery
or inconclusive), supporting artifacts, affected recipients, observed actions and recommended
next collection. Keep addresses, subject, tokens and attachment contents in the private case.

## Message and MIME coordinates

| Evidence location | Exact fields / representation | Correlation / measurement | Validation / limit |
| --- | --- | --- | --- |
| `.eml` or raw RFC message | `From`, `Sender`, `To`, `Cc`, `Bcc` when retained, `Reply-To`, `Date`, `Message-ID`, `In-Reply-To`, `References` | Preserve all repeated headers and original bytes; relate reply identifiers without assuming uniqueness | Visible recipients can differ from SMTP envelope recipients. Missing `Bcc` is normal for many delivered copies. [Message format](https://www.rfc-editor.org/info/rfc5322/) |
| MBOX export | Message separator lines and per-message bytes; keep mailbox hash and message ordinal/byte range | Count messages using the actual MBOX variant before counting MIME parts | `From ` separators and escaping differ from the `From:` header; naïve line splitting can corrupt bodies. MSG/PST/OST are different binary containers. [MBOX format](https://www.rfc-editor.org/info/rfc4155/) |
| Transport trace headers | Repeated `Received` with `from`, `by`, `with`, `id`, `for` where present and trailing date; `Return-Path` | New hops prepend records; trusted receiving infrastructure and queue IDs establish the reliable portion of chronology | Preserve sender `Date` separately. A hostname written in a Received line is not proof that the named server generated it. [Trace fields](https://www.rfc-editor.org/info/rfc5322/) |
| Authentication assertion | `Authentication-Results`: `authserv-id`, method/result pairs, properties such as `smtp.mailfrom`, `smtp.helo`, `header.d`, `header.from` | Associate the assertion with the organization's verified receiver/trace and header-handling policy | Do not trust a sender-supplied assertion just because its `authserv-id` looks familiar; missing, none, fail and temporary error are different outcomes. [Authentication-Results](https://www.rfc-editor.org/info/rfc8601/) |
| MIME part header | `Content-Type` and `charset`/`boundary` parameters, `Content-Transfer-Encoding`, `Content-Disposition`, `Content-ID` | Use message coordinate + MIME part path; retain declared type and decoded-byte digest separately | Decode transfer encoding before interpreting character encoding. A filename is metadata, not a safe output path or proof of content type. [MIME encoding](https://www.rfc-editor.org/info/rfc2045/), [disposition](https://www.rfc-editor.org/info/rfc2183/) |
| Multipart or nested message | `multipart/alternative`, `multipart/mixed`, `multipart/related`, nested `message/rfc822`; CID references to `Content-ID` | Count leaf parts separately from logical attachments and embedded messages | Alternative plain/HTML renderings are not two separate messages; malformed boundaries or resource caps make enumeration partial. [MIME media types](https://www.rfc-editor.org/info/rfc2046/) |
| Attachment bytes and links | Declared filename, media type, encoded/decoded sizes, SHA-256; HTML display text, literal `href`, wrapper URL, observed redirect if independently recorded | Bind every digest/URL to message + part; compare exact bytes and algorithm | Inline content may have a filename, and an attachment may lack one. Do not count a filename predicate as a universal attachment definition; no active rendering or destination fetch is needed |

## Authentication means a particular identity passed a particular check

| Mechanism / source | Fields that matter | Compare | Limit |
| --- | --- | --- | --- |
| SPF result from trusted receiver | SMTP client IP, envelope MAIL FROM domain; HELO identity when applicable | Match the receiver's recorded identity and result, not merely visible `From` | SPF pass does not authenticate message text or the displayed author. Forwarding can alter the evaluated sender path. [SPF](https://www.rfc-editor.org/info/rfc7208/) |
| `DKIM-Signature` | `d`, `s`, `a`, `c`, `h`, `bh`, `b`; optional `l` and time fields | A verified signature binds the signed headers/body domain and selector to the reported validation | A signature header's presence is not a validated signature; unsigned or length-excluded content needs separate review. [DKIM](https://www.rfc-editor.org/info/rfc6376/) |
| Receiver DMARC evaluation | Visible From domain and aligned SPF or DKIM identity; recorded policy/result | Preserve alignment mode and the authenticator's evidence | Domain alignment is not a benignness verdict; policy is not necessarily the receiver's final disposition. [DMARC base specification](https://www.rfc-editor.org/info/rfc7489/) |

## Provider telemetry: message identity is not delivery identity

| Source table | Concrete columns | Join / count unit | Validation / limit |
| --- | --- | --- | --- |
| Defender `EmailEvents` | `Timestamp`, `NetworkMessageId`, `InternetMessageId`, `RecipientEmailAddress`, `SenderFromAddress`, `SenderMailFromAddress`, `SenderIPv4`, `DeliveryAction`, `DeliveryLocation`, `AuthenticationDetails` | Keep tenant + network message + recipient and delivery time; correlate the RFC Message-ID with `InternetMessageId` when valid | One internet message can have multiple recipient/delivery records. Quarantine, delivery and later remediation are separate actions. [EmailEvents](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-emailevents-table) |
| Defender `EmailUrlInfo` | `NetworkMessageId`, `Timestamp`, `Url`, `UrlDomain`, `UrlLocation` | Join URLs to message context while preserving several URLs per message | A URL extraction is not a click. Joining to recipient rows multiplies combinations; state that denominator. [EmailUrlInfo](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-emailurlinfo-table) |
| Defender `EmailAttachmentInfo` | `NetworkMessageId`, `RecipientEmailAddress`, `FileName`, `FileType`, `SHA256`, `FileSize`, `Timestamp` | Match message/recipient plus attachment evidence; sizes are bytes | Identical hashes across messages can be the same file in separate deliveries; absence of a hash does not mean no attachment. [EmailAttachmentInfo](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-emailattachmentinfo-table) |
| Defender `UrlClickEvents` | `Timestamp`, `NetworkMessageId`, `AccountUpn`, `Url`, `ActionType`, `Workload`, `IPAddress`, `IsClickedThrough`, `ReportId` | Preserve click record and account/time rather than collapsing into the message row | Not every workload has mail-message context. Scanning, policy evaluation and user activity need differentiation; a click alone is not compromise. [UrlClickEvents](https://learn.microsoft.com/en-us/defender-xdr/advanced-hunting-urlclickevents-table) |

A header-only export cannot establish attachment completeness. A parser that reports header presence,
addresses, MIME leaves and authentication strings is a triage inventory; it has not independently
verified DKIM, SMTP delivery, human reading or endpoint execution. Keep that distinction in the report.

## Thunderbird OpenPGP acceptance metadata

Resolve `{acquired-thunderbird-profile}/openpgp.sqlite` from the actual profile configuration and acquisition, retaining database/sidecar hashes. The [versioned database module](https://github.com/mozilla/releases-comm-central/blob/c3c7f562cb0e/mail/extensions/openpgp/content/modules/sqliteDb.sys.mjs) defines `acceptance_decision(fpr, decision)` and `acceptance_email(fpr, email)`. All four columns are non-null TEXT; the former has unique `fpr`, the latter unique `(fpr, email)`. Verify these tables in the acquired schema before joining on `fpr`; one fingerprint may have multiple email associations. Profile-relative SQLite path resolution is described by the [underlying storage module](https://github.com/mozilla-firefox/firefox/blob/FIREFOX_128_0_RELEASE/toolkit/modules/Sqlite.sys.mjs).

These are local acceptance records. Preserve the raw `decision` and compare its meaning with the installed revision. This schema declares no event-time column: database filesystem modification time is not a per-row acceptance timestamp. A stored decision does not independently verify a person's identity, a message signature, delivery or reading. Do not describe this database as a decrypted message archive or infer private-key contents from its filename. Keep fingerprints and email values in restricted evidence; this locator does not provide a decoder or a key-recovery procedure.
