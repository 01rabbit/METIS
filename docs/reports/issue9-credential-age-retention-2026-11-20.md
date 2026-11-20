# Issue #9 local credential age retention

This increment adds an explicit, preview-first retention operation for
credentials stored by `metis web auth`.

```sh
metis web credential-retention --older-than-days 90
metis web credential-retention --older-than-days 90 --apply
```

The default preview opens a read-only SQLite transaction and reports counts
without origins or credential values. Apply uses `BEGIN IMMEDIATE` and
`secure_delete=ON`, retires only records with a known timestamp at or before
the cutoff, advances each affected auth generation, and removes only the
matching authentication-origin cookie jar from linked runs. The operation is
bounded to 100 credential origins and 1,000 linked runs; overflow fails before
commit. Any failure rolls back credential deletion, generation changes, and
cookie updates together.

New and replaced credentials receive an `updated_at` timestamp. Existing rows
gain a nullable column during schema migration; their age remains unknown and
they are preserved until an operator reauthenticates or explicitly forgets
them. Environment credentials are not modified. The operation makes no
provider calls and does not claim provider revocation, physical erasure from
WAL/snapshots/backups, encrypted storage, or compliance with a retention
policy. Issue #9 remains open.

Synthetic local tests cover the exact cutoff, read-only preview, legacy
unknown-age migration, reauthentication timestamps, selective cookie removal,
stale-client fencing, rollback, CLI preview/apply behavior, and both operation
bounds.
