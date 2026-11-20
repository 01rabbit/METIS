# Issue #9 local credential age retention

This increment adds an explicit, preview-first retention operation for
credentials stored by `metis web auth`.

```sh
metis web credential-retention --older-than-days 90
metis web credential-retention --older-than-days 90 --apply
```

The default preview opens a read-only SQLite transaction and reports counts
without origins or credential values. When a WAL database has no uncheckpointed
frames, it uses immutable read-only mode and creates no sidecars. With
uncheckpointed WAL frames, it uses SQLite's read-only WAL path; SQLite may
create or update `-wal`/`-shm` coordination sidecars, so the database directory
must be writable. A directory permission failure is reported explicitly. A
pending rollback journal is refused. Checkpointed immutable snapshots are
rejected if their database files change during the read. Apply uses `BEGIN IMMEDIATE` and
`secure_delete=ON`, retires only records with a known timestamp at or before
the cutoff, advances each affected auth generation, and removes only the
matching authentication-origin cookie jar from linked runs. The operation is
bounded to 100 credential origins and 1,000 linked runs; overflow fails before
commit. Any failure rolls back credential deletion, generation changes, and
cookie updates together.

CLI previews do not construct the mutating workflow or migrate the database.
An absent database yields an empty preview without creating its parent path;
legacy credential rows without timestamps remain age-unknown without schema
changes. Relative database paths are supported, and concurrent workflow startup
serializes the credential-column migration.

New and replaced credentials receive an `updated_at` timestamp. Existing rows
gain a nullable column during schema migration; their age remains unknown and
they are preserved until an operator reauthenticates or explicitly forgets
them. Environment credentials are not modified. The operation makes no
provider calls and does not claim provider revocation, physical erasure from
snapshots/backups, encrypted storage, or compliance with a retention policy.
After storing, forgetting, or applying retention, METIS closes the transaction
connection and attempts a bounded `wal_checkpoint(TRUNCATE)`. The result includes
`wal_cleanup_complete`; a concurrent reader can prevent truncation, and false
is reported without undoing an already committed deletion. Repeating `--apply`
retries the checkpoint even when the credential was already removed. A successful
checkpoint covers the active SQLite database only; it does not erase copies in
snapshots, backups or storage media, nor values already loaded by other
processes. Issue #9 remains open.

Synthetic local tests cover the exact cutoff, row-read-only preview and its WAL
sidecar requirement, legacy
unknown-age migration, reauthentication timestamps, selective cookie removal,
stale-client fencing, rollback, CLI preview/apply behavior, and both operation
bounds. Additional CLI regression cases verify that previews leave missing and
legacy databases untouched, accept relative paths, and coexist with concurrent
schema migration. WAL tests cover successful truncation after retirement, a busy
reader followed by a successful retry, and triggers that suppress required
updates or deletion; those cases abort instead of reporting successful retirement.
