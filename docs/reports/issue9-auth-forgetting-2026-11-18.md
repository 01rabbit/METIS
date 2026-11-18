# Issue #9 local web-auth forgetting increment

This increment closes a local credential reuse gap in `metis web forget URL`.
Before this change, the command removed the saved credential row but an existing
web run could reload and send a previously persisted authentication-origin
cookie.

`WebWorkflow.forget_auth` now performs one SQLite write transaction that bumps
the origin's authentication generation, removes its local credential record,
and clears that origin's persisted cookie jar and cookie fingerprint from every
matching web run. Each `SafeHTTP` client checks its captured generation before
sending to the authentication origin. A client created before forgetting is
therefore rejected, including when used by a submit/catalog path. Saving stale
client state is fenced in a write transaction so it cannot restore that
origin's cookies. Other origins' cookie jars and DNS pins are retained.

The regression fixture installs a synthetic authentication cookie, creates a
stale client, forgets the origin, verifies the stale client cannot issue an
authentication-origin request, then simulates stale state persistence and
checks a fresh request sends no cookie. It also checks that a repeated forget
reports no further local credential removal. No real credential or external
provider is used.

Validation status at this report revision: `git diff --check` and Python
syntax compilation passed locally. The focused and full test suites were not
run locally. Exact-head GitHub CI for the branch is running and must pass before
this change is treated as validated.

This is local METIS state management. It does not revoke a token or cookie at a
CTF provider, erase SQLite WAL pages or backups, clear user-managed environment
variables, cancel a request that passed the generation check before forgetting,
or complete the broader P8 gate. Host reboot, end-to-end signed release and
provenance, unified monitoring and retention controls, provider-side
revocation, and the P7 dependency remain outstanding. Issue #9 stays open.
