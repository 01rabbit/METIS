# Codex-native CTF workflow

## Result

METIS now supports a generic authorized CTF loop inside Codex: acquire a
statement and distributions from a URL, analyze bounded inputs, submit to an
official verifier, revise an incorrect hypothesis, and preserve abstract
evidence-backed techniques for later problems. Codex itself supplies reasoning;
no separate model API or Docker service is required.

## Local end-to-end rehearsal

A local CTFd-shaped server generated private random answers and exposed only
problem statements, Base64 distributions, and the official attempt endpoint.
The following behavior was observed through the same public CLI used for a CTF:

1. Problem 1 and its distribution were acquired by URL.
2. The attachment was decoded with a bounded native tool.
3. An intentionally overlong answer containing the explanatory label was
   rejected by the official endpoint.
4. METIS recorded the observed failure, a revised hypothesis, and a materially
   different next action.
5. The exact extracted token was accepted and the run became verified/solved.
6. Abstract success and failure cards were stored without answer material.
7. Problem 2 intake retrieved both cards; the applicable technique was checked,
   and the second official submission succeeded on its first attempt.

This validates state transitions and knowledge transfer on synthetic fixtures.
It is not a benchmark of unseen tasks or a claim about general solve rate.

## Validation

Executed on the cloud Linux checkout:

```text
python3 scripts/setup.py --dev                         passed; doctor ready
pytest -ra                                             156 passed, 8 skipped
ruff check src tests scripts                          passed
mypy src/metis                                        passed (22 files)
fresh feature-branch clone + setup + doctor            passed
fresh-clone Codex/web focused tests                    14 passed
```

The eight skipped tests belong to the optional Docker runner and require a
locally pinned image plus enforced cgroups. They do not cover the default
Codex-native path.

## Security and practical limits

HTTP access uses an explicit origin scope, bounded redirects and bodies, DNS
rebinding checks, normal proxy settings, and TLS validation. Credentials and
cookies are kept in a private local database and omitted from observations.
Attachments are opened through descriptor-based path checks and are parsed
statically within size/time bounds. Candidates and raw private observations are
not stored in reusable technique cards.

Untrusted programs are never executed on the host. Dynamic pwn/reverse tasks
therefore require a separately enforced sandbox. Generic HTML verification also
requires an explicit form field and trusted correct/incorrect result marker;
unknown output fails closed. JavaScript-only pages and non-CTFd APIs may require
a new adapter.
