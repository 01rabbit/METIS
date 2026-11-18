# Locate the exact evidence before interpreting it

Use this contract when acquiring evidence, assigning a worker or reporting an answer. These are
analyst record fields, not a claim that every METIS parser already emits this entire schema.
Keep the filled record in the private case. A path in a handbook is a discovery hint; replace it
with the path and field actually observed in this case.

## Three locations must remain distinguishable

| Coordinate | What to record | Why it changes the conclusion |
| --- | --- | --- |
| Source location | Device/tenant identifier and original filesystem path, provider log channel, index or object key | A renamed download is not the original filename; a collector's folder is not a host persistence location |
| Acquired artifact | Exact private path, byte count, acquisition timestamp and SHA-256; associated sidecar/segment hashes | Another analyst must open the same bytes, including the WAL or image segment needed to decode them |
| Observation within it | The format-specific coordinate below, original field name, raw value/type and parser version | A filename or screenshot alone cannot identify the value used in a decision |
| Derivation | Selection interval, filters, join keys, units/epoch, normalization and resulting value | Readers need to reproduce a transformation without treating the derived value as source text |
| Coverage | Selected and examined populations, skipped records, parser errors, sampling/pagination and limits | No matching row is meaningful only inside the verified population |

Do not replace an unknown source location with the local acquisition path. Mark that relationship
unknown and request the collector manifest. Keep a full internal coordinate even when a report
uses a privacy-preserving evidence ID; resolve the ID through the private manifest.

## Choose a coordinate that survives a second analyst

| Artifact | Minimum locator and selected value |
| --- | --- |
| Plain text or JSONL | Artifact hash, line number with its base stated, byte span when available, and parsed field; do not count wrapped display lines |
| JSON | Artifact hash plus a JSON Pointer to the exact value and its type; array index is zero-based |
| CSV/TSV | File hash, delimiter/encoding, header occurrence and logical record number; quoted embedded newlines are not new records |
| SQLite | Hashes of the acquired DB and available sidecars, schema/table, primary key or documented row identity, column and read query |
| Windows event XML | Export hash, event ordinal, provider, channel, computer, EventRecordID, EventID and named EventData field; a record ID alone is not globally unique |
| Registry export | Hive identity/hash, resolved control set where relevant, key path, value name, type and data; key last-write is a different field |
| PCAP/PCAPNG | Capture hash, interface/capture point, frame number, direction, protocol field and stream/transaction association |
| Mail | Message artifact hash and message ordinal, header name plus repeated occurrence, or MIME part coordinate and decoded-content hash |
| Archive or forensic image | Container/segment hashes, volume identity, full internal member path plus entry ordinal/offset; duplicate names need disambiguation |
| Binary or memory | Image hash, architecture, address space, process identity, VA/RVA/file-offset convention, byte length and symbol/parser version |
| SIEM/API | Tenant and dataset, absolute interval/timezone, saved query text, response/job ID, page/cursor and original event identifier |
| Screenshot/PDF | Original hash, page/frame and bounding region, rendered field label and verified transcription; OCR uncertainty stays visible |

A JSON Pointer uses `/` to separate tokens: `/records/2/byte_count` identifies one value in an
array inside a root object. Escape a literal `~` in a key as `~0`, and a literal `/` as `~1`.
Do not normalize key case or Unicode to make an absent field appear present. These rules come
from [RFC 6901](https://www.rfc-editor.org/info/rfc6901/); they are citation notation, not
additional selector syntax accepted by METIS's `--field` option.

## From a clue to a reproducible finding

1. Inspect one bounded raw record and its schema. Record the actual source label and field names.
2. Check the relevant specialist table for collection prerequisites, epoch and entity semantics.
3. Select the exact population and save the query/extraction parameters privately.
4. Join only on documented keys with source/time context; account for missing and many-to-many matches.
5. Reopen the selected record using its coordinate. Preserve conflicting values and the original representation.
6. Return the value, coordinate, derivation and coverage limit. State the additional artifact needed if it is unresolved.

For example, choosing a maximum JSON value requires the direct numeric field and records
container, not merely a statement that the file contains large numbers. The bundled reader
exposes `data.numeric_selection.maximum_record_indexes` and `maximum_lexemes`; re-check those
rows in the input. Its `source.sha256`, `reader_version`, `complete_for_input`, `limitations`
and `observed_records` describe the read. The caller must separately retain the input path
and acquisition manifest. See [reader output](../../../docs/artifact-tools.md).

## Time-series values and their origin

Use the acquired export's actual schema and producer documentation to determine whether a
value was measured, estimated, interpolated, substituted or later overwritten. Retain the
record locator, raw value, event time and any existing quality/provenance fields with their
documented meaning; do not invent a standard column or classify origin from a plausible
number. If that information is absent, origin remains unknown. Compare an independent
sensor/controller record or retained revision where available, aligning clock and coverage
before joining. Missing communication and a changed physical process are separate claims;
a smooth series does not establish measurement integrity.

## Preserve general facts without publishing private case paths

A reusable reference retains real product fields, default locations, event IDs, units and joins.
A case retains its actual hostname, mounted image root, user profile, index alias, object key and
observed value. Substituting a neutral placeholder in a handbook never authorizes guessing that
placeholder during analysis. If the supplied evidence uses a different schema, report the
observed mapping and its verification rather than silently substituting a familiar field.
