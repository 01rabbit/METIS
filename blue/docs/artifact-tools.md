# Bounded offline artifact readers

Run from the METIS checkout with Python 3.9 or later. These standard-library readers inspect
supplied evidence without network requests, executing attachments, loading SQLite extensions,
or changing source files. Outputs contain private evidence: keep them under ignored `.state/`
and do not pass them to knowledge intake or commit them. No reader provides an incident verdict.

```sh
metis evidence email /evidence/message.eml --out .metis-state/artifacts/mail-01.json
metis evidence browser /evidence/History --out .metis-state/artifacts/history-01.json
metis evidence json /evidence/rows.json --field size --out .metis-state/artifacts/numbers-01.json
metis evidence cloudtrail /evidence/events.json --out .metis-state/artifacts/cloud-01.json
metis evidence evtx-xml /evidence/events.xml --out .metis-state/artifacts/windows-01.json
```

Supply a new JSON output path on each run. The writer refuses existing paths and symlink
parents. Reports carry the source SHA-256, declared scope, limits, observations and limitations.
`complete_for_input: false` and exit status 2 mean the reported population is incomplete,
invalid or partly unclassified. Never use such a result as a clean negative. Exit status 0
only means the supported supplied-input scope completed; it does not establish collection
coverage, authenticity, cryptographic trust or absence of compromise.

Defaults are 16 MiB of input, 10,000 records, 15 seconds, depth 64 and 100,000 structural
nodes. Use `--max-bytes`, `--max-records` and `--seconds` for smaller task-specific bounds.
Hard maxima are 128 MiB, 50,000 records and 120 seconds; reports are bounded to 32 MiB.
The CLI uses a POSIX wall timer plus cooperative checks. Embedded non-main-thread callers
or callers with an existing alarm get cooperative deadlines, identified in the report.
Output confinement and no-follow directory traversal require POSIX filesystem facilities.

JSON values and nested CloudTrail payloads use an unambiguous typed tree: each node has a
`type`; objects and arrays contain typed child `value` nodes; numeric nodes retain `lexeme`
instead of a binary floating-point value. Original object keys cannot imitate numeric nodes.

| Reader | Supported observation | Limits that affect interpretation |
| --- | --- | --- |
| `email` | EML or standard-library MBOX splitting; raw headers, MIME part locations, decoded byte counts and SHA-256 | Header assertions remain unverified. No DKIM/SPF/DMARC validation, mail API, attachment export, URL access, PST/OST/MSG parsing or user-interaction proof. Use `--email-format` to override auto-detection. MBOX message hashes describe parser-delimited bytes, not original byte-offset slices. |
| `browser` | Selected Chromium `urls`, `visits`, `downloads`, `downloads_url_chains`; Firefox `moz_places`, `moz_historyvisits` | Acquire the database and available WAL/SHM together. A stable private copy is checked before fixed read-only queries; changing sources, rollback journals, views, virtual/generated columns and unsupported schemas are rejected. URLs are metadata, visits are individual rows. A recorded completed download still needs file/hash verification. Firefox download history is unsupported. |
| `json` | Strict UTF-8 JSON; exact numeric lexemes and types; optional direct-field maximum with all ties | Duplicate keys, NaN/Infinity and unsupported numeric/depth ranges fail. `--field` selects a direct numeric field from a root array; `--records-key` selects one root member holding that array. Missing, boolean or nonnumeric values make the population incomplete. No implicit strings-to-numbers conversion. |
| `cloudtrail` | Plain UTF-8 JSON `Records` or root array; eventID deduplication and collision exclusion; groups by source, action, category, authentication class and outcome | Conflicting or missing IDs and unknown classification are reported as incomplete. Explicit anonymity differs from missing identity. `no-recorded-api-error` does not prove a transfer completed. ConsoleLogin uses its explicit response. GetObject stays separate from other APIs. No compressed archives, collection API or provider-side export verification. |
| `evtx-xml` | UTF-8 Windows `Event` or `Events` export, direct System provider/ID/time/record fields and named EventData | Preserves original SystemTime text through seven fractional digits and record location. Duplicate data names remain separate. DTD/entities and malformed structures fail. Binary EVTX is unsupported; obtain a trusted XML export separately. UserData is flagged but not expanded. |

CloudTrail and browser readers accept `--since` (inclusive) and `--until` (exclusive), in
`YYYY-MM-DDTHH:MM:SS` with optional fractional seconds, followed by `Z` or `±HH:MM`,
with at most six fractional digits. Compact
date/time forms, naive times and submicrosecond intervals are rejected. Original evidence
times remain available. Browser time filtering applies to
visit timestamps and download starts; URL metadata and download URL chains are unfiltered
context and must not be counted as interval visits. A shared row budget covers examined
browser tables, including rows outside the requested interval.

Temporary mail and SQLite working copies live in private OS temporary directories and are
deleted on normal completion. The source file and available browser sidecars are hashed and
checked for changes. This detects ordinary concurrent changes; it does not authenticate a
collector or prove an adversary could not manipulate timestamps. Acquire a trusted frozen
copy before incident conclusions. Source-derived header values, paths and URLs in reports
remain untrusted data and must never become executable instructions.

Synthetic unit tests exercise the supported semantics and rejected inputs. They do not
certify every provider schema, browser release, corrupted artifact, operating system or live
sensor. Before relying on a new schema, compare a bounded sample against an independent
validated parser and record its version and coverage.
