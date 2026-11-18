# Exact fields in an intelligence or investigation console

Use authorized read access or an existing export. Preserve retrieval UTC, source URL/API object,
view filters, product/schema version and the exact field label or JSON Pointer. Hash lookup is
not sample upload permission. Do not visit an observed destination merely to confirm it exists.

## File intelligence: distinguish what each value dates

For an existing VirusTotal file object, inspect the returned `data.id`, `data.type` and
`data.attributes`. Field availability depends on the service response and entitlement.

| Attribute | Useful interpretation | What it does not establish |
| --- | --- | --- |
| `sha256`, `size`, `type_description` | Match the retrieved object to the supplied artifact's independently computed identity | A similar name is not the same artifact |
| `first_submission_date`, `last_submission_date` | Earliest/latest service submission timestamps, rendered from UTC epoch seconds | File creation, first execution or earliest global malicious activity |
| `last_analysis_date`, `last_modification_date` | Scan time versus update time of the service object | A new scan does not mean a newly created sample |
| `names`, `meaningful_name` | Reported name alternatives and the service-selected label | The actual path, filename or account on the affected endpoint |
| `last_analysis_stats`, `last_analysis_results` | Aggregate counts and each engine's categorized result | Independent votes, actor attribution or a calibrated probability of compromise |
| `signature_info` when present | Signing-related metadata available in this object | Certificate validity is not artifact creation time or proof that runtime behavior is safe |

These names are defined by the service's [file object reference](https://docs.virustotal.com/reference/files).
Keep a missing attribute distinct from zero or an empty array. Store any returned personal data
only in the private case. Cite both the exact source field and the field's time meaning.

## A report, certificate or alert needs its own coordinates

| Evidence | Values to locate | Correlation requirement |
| --- | --- | --- |
| Threat report | Stable document URL/version, publication/update time, section or page and the exact asserted indicator role | Distinguish observed C2, delivery, redirector, certificate infrastructure and a merely mentioned host |
| X.509 certificate | DER hash, serial number with issuer, subject attributes, `notBefore`, `notAfter`, `subjectAltName` when present | A subject `localityName` is a claimed attribute, not endpoint geolocation; validity is not first-seen |
| EDR process graph | Host/device ID, event ID, process entity ID or PID plus start time, parent identity, raw image and command line | Display names or graph positions are not durable join keys; reopen the underlying event |
| SIEM result view | Tenant, index/table, absolute time bounds, query revision, page/cursor, event ID and raw field path | Rendered counts can differ from the exported population; document sampling and caps |
| Scored answer control | Current instance ID, stable question ID, visible label, exact candidate reference, observed result and attempt counter | Current input position is not a question identity; accepted status must belong to this exact instance and question |

Certificate structure is described in [RFC 5280](https://www.rfc-editor.org/info/rfc5280/).
For product-specific event fields use the [SIEM references](../../soc-siem-hunt/SKILL.md).
Console screenshots supplement a saved value/coordinate; they do not replace exact raw fields.

## First observations in distinct services

For a VirusTotal file response, `data.attributes.first_seen_itw_date`, when present, dates
the service's in-the-wild observation; retain its integer UTC epoch-seconds value separately
from `first_submission_date`. Missing observation data cannot be replaced with the submission
clock. Preserve the exact returned field and object identity, because sensor coverage and
response availability limit the meaning of an earliest observation.
[Complete file attribute index](https://docs.virustotal.com/docs/file-attributes-full-list),
[file object](https://docs.virustotal.com/reference/files).

MalwareBazaar `data[].first_seen` is a UTC date-time string for that service's first
observation. Keep `sha256_hash` with it and preserve `last_seen` separately when returned.
The JSON member is `first_seen`, even if a rendered label or another service omits the underscore.
[MalwareBazaar response fields](https://bazaar.abuse.ch/api/).

URLhaus URL records expose `date_added`, a human-readable UTC timestamp for addition to the
service. Payload records use `firstseen` for the service's file observation; keep the URL
record identity separate from payload `sha256_hash`. These fields do not date the first
malicious action, local execution or original file creation. Response containers vary by
endpoint, so retain the full JSON pointer as well as the field label.
[URLhaus response schemas](https://urlhaus-api.abuse.ch/).

## Descriptive metadata in acquired HTML

For a preserved page, locate the `meta` element in the document head whose `property`
attribute is `og:description`, then retain its `content` text with the document hash and
DOM/byte coordinate. This optional Open Graph value is a publisher-supplied description;
it is not a standard account-creation timestamp or a verified identity attribute. Record
page origin and collection time separately from dates asserted within the text. Search
snippets are separately derived observations and may omit, alter or outlive that value;
a matching phrase does not establish contemporaneous page contents or a person's identity.
[Open Graph metadata definition](https://ogp.me/).
