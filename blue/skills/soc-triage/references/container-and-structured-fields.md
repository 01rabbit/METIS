# Concrete coordinates for containers, structured data and Git evidence

This reference supplies field-level inspection requirements. It does not add archive or Git
parsers to METIS. Use a suitable offline reader with bounds; preserve unsupported-format and
partial-read outcomes. [Evidence locators](evidence-locators.md) describe the private manifest.

## Container metadata: locate an entry without trusting its name

| Format and inspection object | Values to inspect | Decision and limitation |
| --- | --- | --- |
| ZIP central-directory entry (`ZipInfo`) | `filename`, `header_offset`, `flag_bits`, `compress_type`, `CRC`, `compress_size`, `file_size` | Bind entry ordinal and header offset to the archive hash; duplicate names are separate entries. A claimed output size is not proof all bytes were decoded |
| ZIP metadata | `date_time`, `extra`, `create_system`, `external_attr` | Directory timestamps are local-time values with limited precision; inspect separately supported extra timestamps. Interpret Unix file-type bits only for the appropriate creator system |
| ZIP structure | Central-directory location/count, local-header correspondence and any data descriptor | Reconcile disagreement, unsupported compression/encryption and embedded prefixes before extraction. CRC checks corruption, not authorship |
| TAR `TarInfo` | `name`, `type`, `size`, `offset`, `offset_data`, `linkname`, `pax_headers` | Distinguish regular members, links, extension headers and duplicate paths. A hardlink target is not new independent content |
| TAR ownership/time | `uid`, `gid`, `uname`, `gname`, `mode`, `mtime`; `TarInfo.mtime` is an integer or float counting seconds since the Unix epoch (1970-01-01 UTC) | Preserve PAX overrides and fractional time where supported; archive metadata can be supplied by its creator |
| GZIP member | `MTIME`, optional `FNAME`/`FCOMMENT`, trailer `CRC32` and `ISIZE`, member boundaries | `ISIZE` is modulo 2^32, not an expansion cap. `MTIME` is a 4-byte little-endian Unix-seconds value; zero means the timestamp is unavailable, not an observed epoch time. Verify every concatenated member and account for trailing bytes |
| Segmented forensic container | Segment order, native directory entry identity, full internal path, logical size, stream/volume and content hash | All required segments and native verification results are necessary. No universal AD1 byte offset is assumed; tool/version support must be established |

Metadata keys are described by [Python ZIP](https://docs.python.org/3/library/zipfile.html),
[Python TAR](https://docs.python.org/3/library/tarfile.html) and
[GZIP's format specification](https://www.rfc-editor.org/info/rfc1952/). Inspect paths and types
before bounded extraction into a new private directory; never execute extracted content.

## Structured records and exact numerical selection

| Input shape | Exact coordinate or field | Required interpretation |
| --- | --- | --- |
| Root JSON array | Zero-based row index and the selected key | Booleans and numeric-looking strings are not numeric JSON tokens |
| Root object holding records | Root member name, then row index, then direct selected key | METIS `--records-key` selects one root array and `--field` one direct numeric key; neither accepts a dotted path traversal |
| Numeric result | `data.numeric_selection.selected[].record_index`, `number_type`, `lexeme` | Retain original digits/exponent and use exact decimal comparison; do not round through binary float |
| Maximum/ties | `maximum_record_indexes`, `maximum_lexemes`, `invalid_record_indexes` under `data.numeric_selection` | Preserve every tied row. An invalid selected row makes the population incomplete even if other maxima are available |
| Typed JSON tree | `data.value`; each node's `type`, object/array `value`, numeric `lexeme` | Parser wrappers describe the value type; they are not source object keys or evidence fields |
| JSON-RPC request | `jsonrpc`, `method`, `params`, typed `id`; enclosing batch ordinal | An absent `id` denotes a notification. Batch positions do not join requests and responses |
| JSON-RPC response | Typed `id`, `result` or `error`; `error.code`, `error.message`, optional `error.data` | Match the ID within the observed connection/session and request scope. Reused IDs create ambiguity; HTTP success is not RPC success or proof of the downstream effect |

The bundled [reader contract](../../../docs/artifact-tools.md) supplies the concrete output
shape; [JSON-RPC 2.0](https://www.jsonrpc.org/specification) supplies the protocol fields.
Duplicate JSON keys and unsupported encodings are parse failures, not an opportunity to select
a convenient value. Keep raw-row counts distinct from deduplicated events and successful effects.

## Static repository evidence

Use an isolated offline reader and disable hooks, filters, external helpers and automatic
network retrieval. An evidence checkout may carry hostile configuration. Do not check out or
execute it just to inspect a historical blob.

| Coordinate | What to inspect and correlate |
| --- | --- |
| Repository root | `.git` directory versus a `gitdir:` pointer; resolve `commondir` inside the permitted evidence boundary |
| Ref storage | `HEAD`, `refs/heads`, `refs/tags`, `packed-refs`; check whether the repository uses another ref format |
| Available history | `shallow`, `objects/info/alternates`, `objects/pack`; missing required stores or promisor objects prevent full-history claims |
| Commit | Object ID, `tree`, every `parent`, author/committer times and offsets; authored time is not proof of execution or server receipt |
| Tree/blob | Commit ID, full tree path, mode and blob object ID; same blob under another path is a rename/content reuse candidate |
| Finding | Repository evidence ID, commit/parent, path, blob ID and byte/line coordinate | 

A removed secret-shaped string can survive in older or unreachable objects. Record the
category and private reference instead of the value, and never try it against a service.
Check object hash/type/size and all limits before claiming coverage. METIS's own repository audit
is not a general-purpose hostile-repository forensic engine.
The storage coordinates above follow [Git repository layout](https://git-scm.com/docs/gitrepository-layout).

## OCI image history coordinates

For an acquired OCI image layout, select the intended platform from `index.json`, follow its
manifest's `config` and ordered `layers` descriptors, and verify the selected blobs.
In the configuration, `rootfs.diff_ids` lists hashes of uncompressed layer tar content
from bottom to top. A manifest layer digest identifies its stored blob, which may be
compressed; it need not equal the DiffID.

`history` is optional metadata. Its `created`, `created_by`, `comment` and `empty_layer`
fields describe build history, not observed runtime activity. `empty_layer=true` consumes
no rootfs layer; a simple count or index join of every history entry to every layer is
wrong. Preserve absent or inconsistent history as a limitation. A Docker save archive's
`manifest.json` with `Config` and `Layers` is a different envelope: identify the export
format before choosing JSON paths. Never launch the image for inspection.

These rules follow the [OCI image configuration, version 1.1.1](https://github.com/opencontainers/image-spec/blob/v1.1.1/config.md)
and [manifest](https://github.com/opencontainers/image-spec/blob/v1.1.1/manifest.md).
Lower-layer retention and whiteout limits are covered in the
[static analysis handbook](../../soc-malware-triage/references/analyst-handbook.md).

## Intel HEX address records

Preserve each original text record's line number, record type, length, offset, content
and checksum. The length is one byte, offset two bytes, and type one byte, represented
as hexadecimal digits. Validate the declared length and the modulo-256 checksum across
decoded record bytes, including the checksum byte. A valid checksum does not establish
origin or completeness.

Types `00` and `01` identify data and end-of-file records. Address records differ:
`02` is extended segment, `03` start segment, `04` extended linear and `05` start linear.
Do not describe type `03` as start linear. Type `04` supplies the high 16 bits for later
data addresses; type `05` describes a 32-bit entry address, not a new data base.
Keep source line coordinates distinct from reconstructed memory addresses. Track holes
and conflicting overlaps instead of silently filling them; missing bytes are not evidence
of zeroes. A HEX file can omit ELF headers, and target address units require the device
and toolchain contract. Inspect statically without programming a device.
See the [TASKING format reference](https://tasking.com/documentation/arm/reference/objfmt_hex.html)
and [Microchip record types](https://onlinedocs.microchip.com/oxy/GUID-7D8A7AF1-1129-4D0D-858A-CA1007A87857-en-US-3/GUID-5CA0F9FD-D01F-4E8B-9539-FA9D3FBBC271.html).

## Geographic coordinates in acquired JSON

For a GeoJSON object conforming to RFC 7946, retain the case-sensitive `type` and the
complete JSON path to `coordinates`. A `Point` holds one position: an array of numbers
whose first two values are longitude, then latitude, in WGS 84 decimal degrees. An optional
third value is ellipsoidal height in meters. A fourth value has no standardized timestamp
meaning here. Preserve the original array and type before converting or plotting it; do
not reverse values merely because both fall within plausible angular ranges.
[RFC 7946 positions and points](https://www.rfc-editor.org/rfc/rfc7946.html#section-3.1.1)
and [coordinate reference system](https://www.rfc-editor.org/rfc/rfc7946.html#section-4).

For historical API exports, `geo.coordinates` and `coordinates.coordinates` are separate
exploration candidates; an observed `legacy` wrapper adds another path component. Those
names alone do not establish GeoJSON conformance, axis order, units or provider version.
Verify the acquired object's schema and producer documentation before interpreting either
array. Keep an unverified order unresolved instead of borrowing the RFC contract. Missing
or null data in one export does not establish that another acquisition never contained a
location. Bind any coordinate to its original record and acquisition, and distinguish a
recorded location from corroborated physical presence of a person.

## Acquired containerd metadata: resolve the configured store

For a containerd 2.0.4 acquisition, resolve the effective configuration and process/service
arguments: `/etc/containerd/config.toml` is a default candidate, while `--config`, `--root`
and `--state` can change locations. Persistent `root` and ephemeral `state` have different
roles. Under the documented `/var/lib/containerd` root, inspect
`io.containerd.metadata.v1.bolt/meta.db`; the overlayfs snapshotter separately uses
`io.containerd.snapshotter.v1.overlayfs/metadata.db` and `snapshots/`. These are distinct
stores, and the metadata plugin opens `meta.db` with bbolt, not SQLite.

Bind any observation to the acquired file hash, configured root, plugin, runtime version
and full bucket/key coordinate. In this version's implementation, the metadata schema
bucket is `v1`; its `version` value is a schema revision, not a container namespace.
Within an actual namespace, `containers/{container-id}` carries fields such as `image`,
`snapshotter` and `snapshotKey`. The image-object bucket is spelled `images` by the code,
although an adjacent schema comment uses singular `image`. Preserve that distinction when
choosing a reader. A container image name, image digest, snapshot key and numeric snapshot
directory are different identities; do not join them by guessed string equality.

Inspect consistent acquired copies with a version-aware bounded reader. Do not open or
watch the production database in place: locking and cleanup interactions can affect the
service. Keep undecoded values and binary time representations unresolved until the
specific reader/writer contract is verified. Stored configuration or retained metadata
does not establish a successful start, current running state or malicious activity.
METIS does not include a bbolt decoder or a live containerd collection connector.

Primary scope: [containerd 2.0.4 storage/configuration](https://github.com/containerd/containerd/blob/v2.0.4/docs/ops.md),
[metadata plugin](https://github.com/containerd/containerd/blob/v2.0.4/plugins/metadata/plugin.go)
and [bucket declarations](https://github.com/containerd/containerd/blob/v2.0.4/core/metadata/buckets.go).
