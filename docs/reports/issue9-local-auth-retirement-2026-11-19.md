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
`forget` and the default `forget-all` remove authentication-origin cookies.
Existing alternate-origin cookies can remain in plaintext on a broadly
accessible database until run state is saved again in environment-only mode
or the operator explicitly retires all run cookies. Neither can undo prior
exposure.
Browser routing checks the stored generation, so a mode switch does not
guarantee cancellation of an already prepared or in-flight browser request.

The check inspects POSIX mode bits and file ownership at each checked operation.
It does not validate ancestor-directory symlinks or ACLs, pin a path between
inspection and opening, erase existing copies, or encrypt files. Treat a
credential already stored with broader permissions as potentially exposed and
rotate it with the provider.

## Retiring all saved run cookies

`metis web --database STATE.sqlite forget-all --include-run-cookies` previews
the number of cookie jars across the selected runs alongside the existing
authentication counts. Add `--apply` to retire saved platform authentication
and all run cookies in one transaction. This retains the existing 100-origin
and 1,000-run limits. The output includes counts and omits origin names and
credential values. The command accepts regular restored SQLite files even when
their permissions are broader than those allowed for local authentication.

The transaction advances a database-wide epoch. In a process that checks
the epoch, a client started before retirement cannot overwrite saved state,
and an intake already underway cannot persist its cookies. Stop pre-upgrade
METIS processes that can write to this database before applying the retirement.
Retiring saved cookies does not cancel in-flight requests, revoke
provider credentials, or modify environment variables. The command performs
no WAL checkpoint, and prior values may remain in SQLite WAL, snapshots,
or backups.

## PR #107 main integration (2026-11-20)

The live PR was already targeting `main` at head
`2f04f8ba6ab3894111d4c4dce824566204cdb04a`. Its prior integration stopped at
`b027449`. After checking the clean worktree and dedicated `agent-01ra66it`
identity, main `abfdce53d4554440090a979826a3786a3c58b7cd` (including #104 and
the previously squash-merged #105) was merged normally into the existing
feature branch. Merge `4eadcf36672332b5aceda77be165dd1a25c894b5` had no
conflicts. No history was rewritten.

The four feature code/test files are unchanged from the pre-integration head;
`git diff --exit-code` over them returned zero. Against the updated main, the
PR retains only its five feature files: this report, `src/metis/cli.py`,
`src/metis/core/ctf_http.py`, `src/metis/core/ctf_web.py`, and
`tests/test_ctf_web_request.py`. Only this integration evidence was added after
the clean merge.

Observed on local macOS arm64/Python 3.12.13 with synthetic credentials and
local/mock HTTP fixtures:

```text
PYTHONPATH=src /Users/mao/Developer/GitHub/METIS/.venv/bin/python -m pytest -o addopts='' -q tests/test_ctf_web.py tests/test_ctf_web_request.py tests/test_cli.py
100 passed in 38.15s
/Users/mao/Developer/GitHub/METIS/.venv/bin/ruff check src tests
All checks passed!
/Users/mao/Developer/GitHub/METIS/.venv/bin/mypy src/metis
Success: no issues found in 112 source files
/Users/mao/Developer/GitHub/METIS/.venv/bin/python scripts/check_repo.py
{"status": "passed", "findings": 0}
/Users/mao/Developer/GitHub/METIS/.venv/bin/python scripts/check_blue_knowledge.py
{"status": "passed", "findings": 0}
git diff --check
```

The PR's current-head GitHub workflow links are recorded in its description.
No live provider credential, external retirement operation, release,
deployment or reboot was used. These integration checks do not change the
retirement limitations or establish Issue #9 acceptance.
