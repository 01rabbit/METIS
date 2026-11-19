# Issue #9: local web-auth retirement boundary

`web auth` replacement, `web forget URL`, and `web forget-all --apply` now
enable SQLite `secure_delete` on the connection before their write transaction.
This asks SQLite to overwrite deleted content in database pages it manages;
it does not erase older WAL frames or copies in snapshots and backups. It is
not an encrypted credential store or a retention timer.

The `forget` response states that provider revocation remains required and
that WAL, snapshots, and backups may retain prior values. `forget-all` exposes
the same boundary only when `--apply` is used; preview has no revocation
action. A new `WebWorkflow` instance over the same database is covered by the
regression test, which confirms that retired local authentication is no longer
sent. This does not exercise a fresh process or reboot.

Operator follow-up for an exposed or retired token is to revoke or rotate it
at the CTF provider, clear any user-managed environment variable, and handle
database copies according to the operator's storage policy. METIS cannot
confirm those external actions. A request already sent before the generation
fence may still have used the former credential. Original and user-added
challenge artifacts are outside `codex purge-derived`; its directory-entry
unlink likewise makes no secure-erasure promise.

This increment does not close Issue #9. Its broader retention, secret storage,
provider revocation, P7, reboot, and release gates require separate evidence.

## Permissions on restored or precreated state

Local web authentication now requires a regular SQLite database owned by the
current user with no group or other permissions. The same checks apply to
existing WAL and SHM files. METIS checks for symbolic links and other nonregular
files at workflow initialization and before authentication or forgetting.
A database restored with broader permissions needs operator review before local
credentials can be used or stored again. The checks do not change existing
file modes.

Environment-only authentication and explicit local forgetting still work with
regular files whose permissions are broader. On such files, environment-only
mode discards cookies from every origin when loading or saving run state.
`forget` and `forget-all` remove authentication-origin cookies. Existing
alternate-origin cookies can remain in plaintext on a broadly accessible
database until the run state is saved again in environment-only mode. That
save cannot undo prior exposure.
Browser routing checks the stored generation, so a mode switch does not
guarantee cancellation of an already prepared or in-flight browser request.

The check inspects POSIX mode bits and file ownership at each checked operation.
It does not validate ancestor-directory symlinks or ACLs, pin a path between
inspection and opening, erase existing copies, or encrypt files. Treat a
credential already stored with broader permissions as potentially exposed and
rotate it with the provider.
