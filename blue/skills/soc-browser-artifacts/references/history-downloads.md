# Offline browser histories and downloads

## Snapshot and database safety

Collect the database with its available WAL and shared-memory sidecars as one coherent
snapshot, recording hashes and acquisition time. An active profile copied piecemeal may
omit recent transactions or contain inconsistent state. Keep originals unchanged and inspect
a separate working copy with no browser process using it.

Use SQLite read-only access and query-only mode. Do not enable extensions or execute SQL
taken from page content. Treat schema objects as untrusted and use bounded queries with a
progress timeout. Immutable mode is appropriate only when the snapshot really is immutable;
it is not a substitute for handling a live WAL-backed database correctly.

Determine the actual schema with table/column inspection before choosing a query. Chromium
commonly separates URLs, visits, downloads and redirect chains; Firefox commonly separates
places from visit records, with version-dependent download representations. Unsupported
schema or missing sidecars is a stated limitation, not an empty browsing history.

## Timestamps and events

Do not mix database timestamp units or epochs. Chromium commonly records microseconds from
1601-01-01 UTC, while Firefox history commonly uses microseconds from the Unix epoch.
Confirm the specific field and validate with a known neighboring event. Preserve the integer
and conversion alongside UTC output; zero and sentinel values are not normal event times.

For each time field, keep five separate entries in the analysis: the schema's fixed epoch,
the unit, the original integer, the converted UTC timestamp and that event's calendar year.
The epoch describes the representation; it does not change when a different event is stored.
Read the requested quantity before calculating: a representation's origin comes from the
field contract, while an event's year comes from its converted timestamp. Check the contract
for every column or JSON property instead of borrowing another field's clock.

Count visit rows separately from distinct URLs. Aggregate visit counts, typed counts and
last-visit fields are not interchangeable with individual visits. Interpret transition
metadata before attributing a navigation to a user: redirects, reloads and background actions
can create records without explicit user action.

## Downloads and reconstruction

Keep the initiating page, requested URL, redirect sequence, response and local destination as
separate evidence roles. A download row can describe cancellation, interruption or a partial
file. Assess status, transferred bytes, completion time and the acquired file's digest.
A URL ending in a filename does not prove that file reached disk.

Relate browser download completion to file creation, security-product scans, media indexing
and subsequent execution. Later indexing time is not the original download timestamp.
Absence of a history entry does not exclude private browsing, another profile, cleared data
or an uncollected device.

Do not open cookie/login stores or recover credentials as part of a history-only task.
Search strings, titles, local paths and URLs may contain personal data or tokens; retain them
only in the private case and use opaque references in reusable lessons.

Finish with a bounded timeline and a list of propositions that the available schema can
support. Include counts of skipped/malformed rows and explain whether the result is complete
for the provided snapshot rather than for all activity on the device.

## Find the correct profile and snapshot

| Browser / default profile root | Evidence file and coordinate | What to correlate | Validation / limit |
| --- | --- | --- | --- |
| Chrome Windows `%LOCALAPPDATA%\Google\Chrome\User Data\`; macOS `~/Library/Application Support/Google/Chrome/`; Linux `~/.config/google-chrome/` | Per-profile `History`, often beneath `Default` or `Profile N`; user-data root holds `Local State` | Record resolved user-data root, profile directory, acquisition time and `History` hash | Flags, policy, channel and packaging can relocate the root. `Default` is a directory label, not proof of which user browsed. [Chromium location contract](https://raw.githubusercontent.com/chromium/chromium/main/docs/user_data_dir.md) |
| Chromium rather than branded Chrome | Windows `%LOCALAPPDATA%\Chromium\User Data\`; macOS `~/Library/Application Support/Chromium/`; Linux `~/.config/chromium/` | Select the per-profile `History` under the actual root | Do not silently search only Chrome's directory when the installed browser is another Chromium product. [Chromium location contract](https://raw.githubusercontent.com/chromium/chromium/main/docs/user_data_dir.md) |
| Firefox Windows `%APPDATA%\Mozilla\Firefox\Profiles\`; macOS `~/Library/Application Support/Firefox/Profiles/`; Linux `~/.mozilla/firefox/` | Per-profile `places.sqlite`; use `profiles.ini`, install/profile metadata and available profile roots | Keep profile identifier with database row IDs; profile names can change | Containerized/package installs and profile configuration may use different roots. A found profile is not automatically the incident profile. [Firefox profiles](https://support.mozilla.org/en-US/kb/profiles-where-firefox-stores-user-data) |
| SQLite snapshot beside `History` or `places.sqlite` | Same basename with `-wal` and `-shm`, when present; `sqlite_schema`; `PRAGMA table_info` on the analysis copy | Keep coherent database/sidecar acquisition and inspect actual columns before joins | Committed pages may still be in WAL. Dropping sidecars or calling a changing copy immutable can hide recent rows. [SQLite WAL behavior](https://sqlite.org/wal.html) |

## Chromium History: one row does not always mean one navigation

| Table / field location | Native columns | Join and time rule | Interpretation / limit |
| --- | --- | --- | --- |
| `urls` | `id`, `url`, `title`, `visit_count`, `typed_count`, `hidden`, `last_visit_time` | URL row ID links from visit rows; last-visit is an aggregate clock | Count URLs separately from visits. `typed_count`/`hidden` are history attributes, not proof of a human typing each row. [URL schema](https://raw.githubusercontent.com/chromium/chromium/main/components/history/core/browser/url_database.cc) |
| `visits` | `id`, `url`, `visit_time`, `from_visit`, `transition`, `visit_duration` where supported | `visits.url = urls.id`; `from_visit` points to a visit ID, not a URL ID | Preserve redirects and automatic transitions. One URL can have many visits, and history expiry can remove related rows. [Visit schema](https://raw.githubusercontent.com/chromium/chromium/main/components/history/core/browser/visit_database.cc) |
| History clocks and transition encoding | `visit_time`, `last_visit_time`; transition core is low 8 bits and qualifiers occupy higher bits | Normal history clocks use microseconds since 1601-01-01 UTC; Unix microseconds = value minus 11644473600000000 | Preserve the integer before conversion; zero/sentinel/out-of-range values remain unresolved. A masked core alone loses redirect qualifiers. [Time representation](https://raw.githubusercontent.com/chromium/chromium/main/base/time/time.h), [transition definitions](https://raw.githubusercontent.com/chromium/chromium/main/ui/base/page_transition_types.h) |
| `downloads` | `id`, `guid`, `current_path`, `target_path`, `start_time`, `end_time`, `received_bytes`, `total_bytes`, `state`, `interrupt_reason`, `opened` | Follow download ID to its URL chain; modern time fields use Chromium's microsecond epoch | Version migrations changed schemas and old time storage. State/bytes/path must be checked together; `opened` is browser metadata, not independent executable-process evidence. [Download schema](https://raw.githubusercontent.com/chromium/chromium/main/components/history/core/browser/download_database.cc) |
| `downloads_url_chains` | `id`, `chain_index`, `url` | `id = downloads.id`; order by `chain_index` to retain initial and redirect destinations | Chain rows multiply downloads. The final URL and a local target path do not prove that all bytes reached disk. [Download schema](https://raw.githubusercontent.com/chromium/chromium/main/components/history/core/browser/download_database.cc) |
| `keyword_search_terms` | `keyword_id`, `url_id`, `term`; `normalized_term` where present | `url_id = urls.id`; retain the associated provider identifier and URL | A stored term is a browser-generated history observation; count distinct terms, URL associations and visits separately. [Search-term structure](https://chromium.googlesource.com/chromium/src/+/a5bd18e21a13b46d1e262ec43ae9fd134c77c978/components/history/core/browser/keyword_search_term.h) |

## Firefox Places and download annotations

| Table / field location | Native columns | Join / clock | Interpretation / limit |
| --- | --- | --- | --- |
| `moz_places` | `id`, `url`, `title`, `visit_count`, `typed`, `hidden`, `last_visit_date`, `guid` | Preserve local ID and profile; GUID is a separate field | Place aggregates do not enumerate individual visits. [Places table definitions](https://searchfox.org/firefox-main/source/toolkit/components/places/nsPlacesTables.h) |
| `moz_historyvisits` | `id`, `place_id`, `from_visit`, `visit_date`, `visit_type` | `place_id = moz_places.id`; `from_visit` refers to another visit; `visit_date` and `last_visit_date` use Unix microseconds | Interpret transition using the browser version. A date conversion with milliseconds instead of microseconds shifts the result by a factor of 1000. [History implementation](https://raw.githubusercontent.com/mozilla-firefox/firefox/main/toolkit/components/places/History.sys.mjs) |
| `moz_annos` plus `moz_anno_attributes` | `moz_annos.place_id`, `anno_attribute_id`, `content`; attribute `id`, `name` | Join place ID to `moz_places.id`, attribute ID to `moz_anno_attributes.id` | An annotation is metadata associated with a place; it is not automatically a separate download attempt. [Places table definitions](https://searchfox.org/firefox-main/source/toolkit/components/places/nsPlacesTables.h) |
| Download annotation names | `downloads/destinationFileURI`, `downloads/metaData`; metadata may contain `state`, `endTime`, `fileSize`, `deleted` | Decode metadata JSON after selecting the attribute name; keep destination URI distinct from local file path | Metadata can be replaced for the same source URL and fields can be missing. Do not apply Places microsecond conversion to arbitrary JSON properties or assume old `moz_downloads` exists. [Download-history contract](https://raw.githubusercontent.com/mozilla-firefox/firefox/main/toolkit/components/downloads/DownloadHistory.sys.mjs) |

For a bounded read, first confirm the named table/columns, then select the matching URL ID and
its visit rows; retain stable row IDs and explicit ordering before applying a row limit. Record
both total matching rows and rows actually retrieved. Reconcile a claimed completed download with
the acquired file, filesystem timeline and relevant security/application logs; history alone cannot
establish that the downloaded program executed.

## Duration and annotation clocks

`visits.visit_duration` is an integer count of microseconds representing a duration. It has
no calendar epoch; applying the history timestamp offset to it is invalid. It measures the
browser's recorded visit duration, not necessarily continuous human attention.
[Visit storage](https://raw.githubusercontent.com/chromium/chromium/main/components/history/core/browser/visit_database.cc)
uses the [microsecond duration binding](https://raw.githubusercontent.com/chromium/chromium/main/sql/statement.cc).

In Firefox `downloads/metaData`, the JSON `endTime` is a numeric Unix-epoch millisecond
value in the implementation that records it from `Date.now()`. `fileSize`, when retained,
is the target size in bytes. Preserve the annotation's `state` and actual browser version:
a stored end time also occurs for unsuccessful or canceled attempts, and some annotations
lack metadata. This clock differs from the microseconds in Places visit columns.
[Metadata persistence](https://raw.githubusercontent.com/mozilla-firefox/firefox/main/toolkit/components/downloads/DownloadHistory.sys.mjs),
[download state updates](https://raw.githubusercontent.com/mozilla-firefox/firefox/main/browser/components/downloads/DownloadsCommon.sys.mjs).

## Preserved Chromium extension metadata

Inspect the acquired profile's `Extensions/{extension-id}/{version}/manifest.json` when
that installation layout is present. Keep the profile, extension ID, version directory,
manifest digest and full member path together. Unpacked or policy-managed installations
may resolve elsewhere; establish the configured location from the acquired state. File
presence establishes available package content, not whether it was enabled or executed.

Record manifest `name`, `version`, `manifest_version` and `default_locale`. A name in
`__MSG_messageName__` form refers to a key in `_locales/{locale}/messages.json`; its
`message` property supplies the text. Use the observed UI locale, then its language and
finally the manifest default according to the supported fallback order. Record which
locale/member resolved the label, and leave missing mappings unresolved. A localized
label, familiar ID or recognized publisher is not evidence that the acquired version is
benign. Keep executable-content assessment separate from package naming.
[Chrome internationalization](https://developer.chrome.com/docs/extensions/reference/api/i18n)
documents the reference syntax, message fields and fallback behavior.

## Saved-login metadata

An acquired Chromium profile can contain a `Login Data` SQLite database. Inspect its
actual `logins` table and schema version before selecting `origin_url`, `signon_realm`,
`username_value` and `date_password_modified`. These identify saved-record metadata;
they do not prove a server accepted a login. The documented `date_password_modified`
column is an integer wall-clock value in microseconds since 1601-01-01 UTC. Preserve
zero/default values instead of treating them as an observed historical event.
The column was introduced in database schema version 30, with older records populated
from `date_created`; that migration is not proof of a password change at the recorded
time. Database synchronization or maintenance is also distinct from interactive use.
Keep secret-bearing blobs in the restricted evidence, not a report.
See Chromium's [login database implementation](https://raw.githubusercontent.com/chromium/chromium/main/components/password_manager/core/browser/password_store/login_database.cc)
and [SQL time binding](https://chromium.googlesource.com/chromium/src/+/HEAD/sql/statement.cc).

## File-transfer client configuration

For an acquired FileZilla Client profile, locate `recentservers.xml` in the configured
settings directory. Do not derive a universal directory from one user's acquisition:
`fzdefaults.xml` can specify a different `Config Location`. Record the resolved path,
file hash and reported version/platform when present. The XML path
`FileZilla3/RecentServers/Server` identifies an entry; `Host`, `Port`, `Protocol` and
`User` are child elements containing configured endpoint/account information.
`Port` and `Protocol` contain numeric text, with protocol interpretation tied to the
client build. Entry presence is not proof of a successful connection or data transfer.

If a `Pass` element exists, record only the necessary storage metadata in the report.
Its `encoding="base64"` describes reversible encoding, not encryption; current source
also supports `encoding="crypt"`. The attribute and client version determine the format;
absence does not prove that no authentication occurred. Preserve secret content only in
authorized private evidence and do not use it to authenticate to a service.
The primary contracts are FileZilla's [recent-list reader](https://svn.filezilla-project.org/svn/FileZilla3/trunk/src/interface/recentserverlist.cpp),
[XML writer](https://svn.filezilla-project.org/svn/FileZilla3/trunk/src/commonui/xmlfunctions.cpp)
and [configuration override documentation](https://filezillapro.com/docs/v3/advanced/how-to-configure-filezilla-pro-defaults-file-fzdefaults-xml/).

## Acquired forensic-export schema candidates

For a supplied forensic SQLite export, including one associated with a MANS acquisition,
first establish the container from its bytes, then inventory its actual tables and columns. The following are exploration candidates,
not a verified universal MANS or browser-native schema:

| Candidate | What to verify in the acquired export |
|---|---|
| `FileDownloadHistory.SourceURL` | Presence, stored type, meaning and originating artifact; a URL value alone does not prove a completed download |
| `EventLogs`, `Processes`, `Ports`, `Files` | Actual table existence and exporter/version identity; table names alone do not define event, process, connection or file semantics |
| `Files.ID`, `Files.FileName`, `Files.FullPath` | Identifier scope, uniqueness, stored types and whether names/paths are original or collector-generated |
| `Files.Created`, `Files.Modified` | Actual types, precision, epoch/timezone and whether the time describes the source filesystem, collection or an export transformation; equal values do not establish causality |
| `FileStrings.FileID` | Whether it really references `Files.ID`; confirm key cardinality and extraction provenance before joining |
| `Threats`, `Alerts`, `IOCData` | Verify table existence, collector/version and native columns before interpreting classifications. Zero rows establish only that this acquired table is empty; they do not prove the source product never recorded a detection or that the evidence is benign |

The product/version contract, column types and time encoding for these candidates remain
unverified; no clock conversion or universal join is defined here. Preserve exporter
version, database/schema hash and original row coordinates. METIS does not provide a
validated parser for this export schema. Missing candidate columns mean the recipe does
not apply, not that the underlying activity was absent. Keep extracted strings and case
values in private evidence.

## Safari history in acquired macOS profiles

Treat Safari's private SQLite layout as a version-dependent reading candidate. Look for
`History.db` beneath the acquired user's `Library/Safari` and
`Library/Containers/com.apple.Safari/Data/Library/Safari`; profile-aware layouts can add
`Profiles/{profile-uuid}/History.db`. Confirm the actual browser/profile, database schema
and matching WAL generation before reading. The independent [mac_apt reader](https://github.com/ydkhatri/mac_apt/blob/master/plugins/safari.py)
uses `history_visits.history_item` to relate visits to `history_items.id`. The
[Plaso reader's declared layout](https://github.com/log2timeline/plaso/blob/main/plaso/parsers/sqlite_plugins/safari.py)
places `url` in `history_items` as TEXT, while `history_visits` owns `visit_time`
(REAL), nullable `title` (TEXT) and `load_successful` (declared BOOLEAN). Both tables
have an INTEGER primary-key `id`; `history_visits.history_item` is an INTEGER item
reference. These are reader-observed schema declarations, not a universal Safari
contract. Verify actual columns, SQLite storage classes and browser version before
using them; a declared BOOLEAN does not justify coercing every unexpected value.
Keep visit row identity separate from URL identity;
several visits may refer to one item. A retained visit does not prove deliberate navigation,
a completed download, or the identity of the human using the profile. This is an external
reader contract, not a bundled METIS decoder or a promise that every Safari build matches it.

For an acquired `visit_time` confirmed to use CFAbsoluteTime, retain fractional seconds
from `2001-01-01T00:00:00Z`; Unix seconds equal that value plus `978307200`.
[Apple's date implementation](https://github.com/apple-oss-distributions/CF/blob/main/CFDate.c)
defines the epoch offset. Do not apply Chromium's microsecond conversion, choose units by
value magnitude alone, or turn a reader's missing-value sentinel into an observed date.

## Chrome native messaging configuration evidence

An acquired extension's `permissions` may declare `nativeMessaging`. For Windows Chrome,
inspect `HKCU\SOFTWARE\Google\Chrome\NativeMessagingHosts\{host-name}` and
`HKLM\SOFTWARE\Google\Chrome\NativeMessagingHosts\{host-name}`. Preserve hive and
registry view: Chrome searches the 32-bit view before the 64-bit view. The default registry
value points to the host manifest JSON; the documented registration uses `REG_SZ`.

Read manifest string fields `name`, `description`, `path`, `type` and the string array
`allowed_origins`. The supported `type` is `stdio`. Resolve `path` against the manifest's
directory when relative on Windows; macOS/Linux require an absolute path. Join an allowed
`chrome-extension://{extension-id}/` origin to the acquired extension ID exactly; wildcards
are not permitted. On macOS/Linux, also resolve the browser's user-data directory and its
`NativeMessagingHosts` subdirectory; system paths differ by browser product. Retain
registration, manifest and referenced-file hashes. These artifacts describe configuration,
not host execution, successful messaging, enabled state or trust. Do not launch a host to
validate the evidence. See the [Chrome native messaging contract](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging).

## Firefox cookie metadata and sensitive profile stores

For Firefox 128.0, `cookies.sqlite` is resolved within the acquired profile root described above. Its `moz_cookies` table declares `id` as an INTEGER primary key; `name`, `host`, `path` and `originAttributes` are TEXT. Keep the complete `(name, host, path, originAttributes)` tuple, which is the unique constraint in this revision, together with the profile/database identity. A name or host alone does not identify a cookie across partition or container contexts. Inspect the actual schema and coherent WAL state before using this contract.

The INTEGER clocks differ: `expiry` uses Unix seconds; `creationTime` and `lastAccessed` use Unix microseconds. The latter can be approximate and includes creation, modification or access; it is not a precise human browsing event. Preserve migration/default/sentinel cases. A retained row is neither proof of a successful server login nor a complete list of past sessions. Do not join its local `id` directly to Places IDs or apply Chromium's epoch.
[Versioned cookie storage and bindings](https://github.com/mozilla-firefox/firefox/blob/FIREFOX_128_0_RELEASE/netwerk/cookie/CookiePersistentStorage.cpp) and [per-field clock contract](https://github.com/mozilla-firefox/firefox/blob/FIREFOX_128_0_RELEASE/netwerk/cookie/nsICookie.idl).

`logins.json` is another profile-relative file; NSS uses `key4.db` within the profile for key storage. These are distinct from the cookie database. Handle them as sensitive acquisition members, outside a history-only task. Keep secret values out of reusable notes; metadata inspection does not authorize credential recovery or session reuse. File presence alone establishes neither use nor compromise.
[Login-store location](https://github.com/mozilla-firefox/firefox/blob/FIREFOX_128_0_RELEASE/toolkit/components/passwordmgr/storage-json.sys.mjs) and [NSS key-store role](https://firefox-source-docs.mozilla.org/rust-components/api/js/db_crypto.html).
