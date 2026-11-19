# Issue #9: loopback operator audit view

`metis operator --database STATE.sqlite --port 0` serves a minimal Japanese
audit page and `GET /api/runs/{run_id}/audit` on `127.0.0.1` only. Set a
32–512-character `METIS_OPERATOR_TOKEN` in the environment before launch;
the server does not generate, print or persist it. The page holds the token
only in its password field and sends it in an Authorization header. The server
logs no requests. API data comes from the existing read-only, count-only
`RunStore.audit_summary`; event details and credentials are not returned.

The HTTP handler checks the loopback Host header, rejects Origin-bearing
requests, omits CORS, sends no-store and restrictive browser headers, and has
no write route. It refuses missing databases, invalid ports and short tokens.
The existing CLI remains the route for cancel and recover; this first
increment does not add pause/resume or HTTP control endpoints.

Local HTTP and audit tests passed (`21 passed`), including unauthorized and
wrong-Host requests, read-only POST refusal, corrupt-chain handling and no
database creation on a missing file. Ruff and mypy passed. This is a local
operator visibility increment, not production readiness or Issue #9 closure.
