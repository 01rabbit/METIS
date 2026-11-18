# Artifact integrity and exact answers

These are analyst requirements, not claims that METIS bundles every parser mentioned below.
Record the tool, version, configuration, input digest, output digest, limits, diagnostics and
coverage in the private case. A successful process exit alone does not establish completeness.

## Intake, archives and forensic containers

Inventory archive members before extraction: names, types, sizes, encryption, expected total
uncompressed bytes and available disk. Reject traversal and unsafe links; extract into a new
private directory, using bounded reads and atomic output replacement. Handle long Windows
paths explicitly. Preserve originals and resumable extraction state tied to their digests.
Partial extraction is not evidence that a file is absent.

For AD1 or another forensic container, use the native integrity verifier and an independent
directory-tree comparison where possible. Compare entry count, full path, type, logical size
and content digest. Account for all segments and parser errors. A plausible directory tree
from a partial or unsupported extractor is not an authoritative complete image.

Do not silently substitute a similarly named file. Bind every result to canonical input
identity and a digest; detect changes between inventory and analysis. Reject symlink escapes
and output paths that overwrite inputs. Keep extracted credentials and personal data private.

## Structured application evidence

Parse JSON-RPC single objects and batches. Join requests and responses on the exact typed ID;
a string ID and numeric ID are different. Preserve unmatched, repeated and ambiguous IDs.
Do not infer method success from a response's existence: evaluate the protocol error/result
and the application outcome. Separate raw records, requests, attempts, sessions and actors.

Ports and endpoints have roles: listener, client, relay and forward destination. Bind them to
a process and direction using evidence. A unique port or nearby timestamp does not establish
a role. Define what “first successful” means before ranking events.

PDF extraction and OCR are lossy. Check rendered pages for wrapping, symbols, omissions and
text order. Preserve the original representation alongside any normalized value.

## Exact numeric JSON analysis

Use decimal lexemes and exact decimal arithmetic for extrema and counts where precision
matters. Binary floating point and JavaScript Number can merge distinct large integers.
Select the records container and direct field explicitly; reject duplicate object keys,
mixed record types, absent required values, non-finite numbers and excessive exponents.
Keep all ties. A linear scan is sufficient; sorting is unnecessary for an extremum.

Bound bytes, nesting, record count and diagnostics. Hitting a bound is an incomplete result,
not a valid maximum over the original population. Re-run the selected record directly from
the unchanged input before reporting. Report the selector and exact original numeric text.

## Static Git evidence and secrets

Treat an evidence repository as hostile. Inspect without checkout, hooks, filters or executing
its scripts. Bound object decompression, total work and ref resolution; verify object type,
declared size and hash. Count corrupt objects against work budgets. Detect ref cycles and
state whether packs, shallow history or alternates are supported. Unsupported storage modes
make coverage incomplete.

A renamed file can retain the same blob. Follow tree history as well as filenames. Findings
about credentials use category, opaque object coordinates and private evidence references;
never publish recovered secret values. Source repositories and case evidence are not copied
into METIS's Git history.

## Queues, interfaces and answer review

Inventory is not a task objective. Each worker receives a specific question, artifact identity,
scope and limits. Associate results with task revision and reservation time; reject stale
results from another attempt or input. Return structured blockers instead of invented answers.
Keep independent analysis parallel and serialize shared external state through the owner.

An unavailable browser is an interface blocker, not negative analytical evidence. Continue
independent offline work. Preserve resumable coverage frontiers and avoid retrying the same
failed subset without a changed condition. Stop obsolete monitors when a case ends.
A tool freeze stops the specified calls; returned results still require reconciliation.

Separate semantic answer selection from formatting. Placeholders illustrate shape, not truth.
Keep hostname versus FQDN, value name versus registry container, display name versus image
path, executable extension, version suffix, URL components and time precision distinct.
Internal timelines use UTC; render the requested representation only after verifying meaning.
A rejected answer can indicate transport, authorization, formatting or evidence errors;
rejection alone does not refute the underlying fact. Do not spray variants across a shared
attempt budget. The owner reconciles evidence and controls authorized submissions.

Prove impossibility using the artifact and constraints, not another analyst's failure.
Use fresh, independent replay for consequential answers. Record uncertainty and a concrete
next evidence request when replay cannot settle a conflict.

## Ext4 evidence images and journal recovery

A filesystem mounted read-only can still cause writes below that interface. Ext4
may replay its journal and update a backing image despite the `ro` option. Preserve
an untouched source and its digest; prefer a verified read-only image reader or
block-level write protection. If a working copy must be mounted, verify the actual
options and backing-device protection. Ext4's `ro,noload` suppresses journal loading;
`norecovery` is another documented name for that behavior. Skipping recovery after
an unclean shutdown can expose an inconsistent filesystem, so missing entries are
not reliable negative evidence. Keep any recovered view separate from the original.
The [kernel ext4 documentation](https://cdn.kernel.org/doc/html/latest/admin-guide/ext4.html)
defines these semantics. Record image, partition/volume, reader/kernel version,
options and before/after hashes. Do not repair or replay original evidence merely
to make a reader succeed.


Transport logs and artifact integrity answer different questions. An RDP log
containing `ERRCONNECT_CONNECT_TRANSPORT_FAILED` can describe session teardown;
classify it against the actual transfer interval and completion records. The
error label alone neither proves nor clears a damaged copy. Compare source and
copy size/hash when available and verify the archive's native structure and
checksums. Elapsed sleep time, filename existence or a case-specific size cutoff
cannot substitute for completion and content validation.

## 7z header coordinates

For the documented 7z signature header, offsets are relative to the archive
origin, which may follow an executable stub. Its fixed header is 32 bytes:
`StartHeaderCRC` occupies bytes 8-11; the following little-endian fields are
`NextHeaderOffset` (uint64, bytes 12-19), `NextHeaderSize` (uint64, bytes 20-27)
and `NextHeaderCRC` (uint32, bytes 28-31). The next header begins at archive
origin plus 32 plus `NextHeaderOffset`. Check arithmetic and bounds against the
acquired size before interpreting that range. `StartHeaderCRC` covers bytes
12-31; `NextHeaderCRC` covers the indicated next-header bytes. These checks do
not validate every packed stream, prove authenticity or reveal encrypted content.
Preserve an encoded-header dependency as unresolved unless the chosen reader
supports it. [7z format](https://github.com/ip7z/7zip/blob/main/DOC/7zFormat.txt),
[7z reader](https://github.com/ip7z/7zip/blob/main/CPP/7zip/Archive/7z/7zIn.cpp).

## Terminal input as an acquisition boundary

A terminal transcript can differ from the bytes offered to its input. Record the
acquired terminal settings and reader mode alongside the transcript, byte counts
and source/copy hashes. In POSIX termios, `ICANON` in `c_lflag` selects canonical
input processing; line delimiters and editing characters can affect delivery.
A defined `{MAX_CANON}` limits the bytes in a canonical line, with behavior beyond
that limit left to the implementation. Do not apply one operating system's numeric
limit to another terminal, or treat a short read as proof of a complete line.

For noncanonical input, the `c_cc` entries indexed by `VMIN` and `VTIME` control
minimum input and timer behavior; the timer unit is one tenth of a second. The
interaction also depends on which values are zero and on `O_NONBLOCK`, whose
precedence over MIN/TIME is unspecified by POSIX. Retain timeout, error and
end-of-input distinctions. A pasted command's apparent arrival or a process exit
does not establish that an artifact survived this transport intact. Use existing
settings and integrity evidence; changing an evidentiary session's terminal mode
is not a substitute for validating the acquired bytes.
[POSIX.1-2017 terminal input rules](https://pubs.opengroup.org/onlinepubs/9699919799/basedefs/V1_chap11.html)
and [termios member definitions](https://pubs.opengroup.org/onlinepubs/9699919799/basedefs/termios.h.html).

## Exif image-generation clock fields

For the Exif 2.3 layout, resolve the image's Exif IFD and retain the tag coordinate, type, count and original bytes before rendering a date. `DateTimeOriginal` is tag `0x9003` (36867), declared `ASCII` with count 20 including the terminating NUL. Its calendar representation is `YYYY:MM:DD HH:MM:SS`, using a 24-hour clock. This field is neither a numeric Unix epoch nor a value carrying its own UTC offset. Preserve blank or unknown components; do not silently supply a zone or replace them with acquisition time.

`SubSecTimeOriginal`, tag `0x9291` (37521), supplies an optional, variable-length ASCII fractional-second component. Interpret its digit precision with the corresponding original date/time; it is not an integer with a universally fixed millisecond unit. Do not attach it to a different date tag merely because the times are close.

These fields describe claimed original-image generation time. Keep them distinct from filesystem timestamps, metadata-edit time and independently observed camera activity. Editable metadata alone cannot establish clock accuracy, an actual capture event or provenance. Record the reader and supported Exif version; this reference adds no image-metadata decoder.
[CIPA Exif 2.3, Table 7 and date/time definitions](https://www.cipa.jp/std/documents/e/DC-008-2012_E.pdf).
