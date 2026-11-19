# Issue #9: local web-auth retirement boundary

`web auth` replacement, `web forget URL`, and `web forget-all --apply` now
enable SQLite `secure_delete` on the connection before their write transaction.
This asks SQLite to overwrite deleted content in database pages it manages;
it does not erase older WAL frames or copies in snapshots and backups. It is
not an encrypted credential store or a retention timer.

The `forget` response states that provider revocation remains required and
that WAL, snapshots, and backups may retain prior values. `forget-all` exposes
the same boundary only when `--apply` is used; preview has no revocation
action. A fresh controller over the same database is covered by the regression
test, which confirms that retired local authentication is no longer sent.

Operator follow-up for an exposed or retired token is to revoke or rotate it
at the CTF provider, clear any user-managed environment variable, and handle
database copies according to the operator's storage policy. METIS cannot
confirm those external actions. A request already sent before the generation
fence may still have used the former credential. Original and user-added
challenge artifacts are outside `codex purge-derived`; its directory-entry
unlink likewise makes no secure-erasure promise.

This increment does not close Issue #9. Its broader retention, secret storage,
provider revocation, P7, reboot, and release gates require separate evidence.
