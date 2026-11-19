# Issue #9: local web authentication replacement

`metis web auth URL` now replaces the saved credential for that origin. Switching
from token to cookie, or cookie to token, no longer retains the previous kind in
`web_credentials`. The same SQLite transaction advances the origin's auth
generation and removes its cookies and cookie fingerprint from existing web
runs. Clients created before replacement are fenced from sending another
request to that authentication origin.

Synthetic local tests exercise token to cookie to token switching, confirm the
request headers and cookies used after each switch, and inspect the active
credential row. The bulk-forget preview test now compares generation state
before and after preview because initial authentication also creates a
generation record.

This controls active local reuse. SQLite historical pages, WAL files, backups,
environment variables, provider-side sessions, and a request that already
passed its generation check are outside this increment. Issue #9 remains open.
