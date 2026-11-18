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

The state load and its authentication-generation read now share one SQLite
read snapshot. A run state carries the generation under which its cookie jar
was loaded; a client created from a pre-forget snapshot remains fenced even if
client construction happens after the forget transaction. Initial intake also
checks the generation in its write transaction before persisting fetched
cookies, closing a separate first-save race.

Regression fixtures install a synthetic authentication cookie and cover both
client-before-forget and state-load-before-forget/client-after-forget
interleavings. They verify that stale clients cannot issue an
authentication-origin request, stale saves cannot restore cookies, and a
forget during intake prevents initial persistence. Fresh requests send no
cookie, and a repeated forget reports no further local credential removal. No
real credential or external provider is used.

The focused web workflow and request suites, Ruff, and mypy passed locally.
Exact-head CI for the preceding code revision found one older intake fixture
whose fake client did not implement the new generation attribute; the fixture
now matches the `SafeHTTP` client interface. CI for that fixture adjustment is
pending.

This is local METIS state management. It does not revoke a token or cookie at a
CTF provider, erase SQLite WAL pages or backups, clear user-managed environment
variables, cancel a request that passed the generation check before forgetting,
or complete the broader P8 gate. Host reboot, end-to-end signed release and
provenance, unified monitoring and retention controls, provider-side
revocation, and the P7 dependency remain outstanding. Issue #9 stays open.
