# P2 offline category fixture coverage

The deterministic smoke test `tests/test_codex_practice_categories.py` uses
`ctf_practice.practice()` to create one local synthetic challenge for each of
crypto, web, forensics, rev, pwn, and misc. It checks explicit local-intake
authorization and exercises the same bounded data transform and artifact
inspection adapters available to specialists. Unsupported data and artifact
operations must fail closed with a controlled reason.

Run with the repository Python 3.12 environment:

```sh
.venv/bin/python -m pytest -q tests/test_codex_practice_categories.py
.venv/bin/python -m pytest -q tests/test_codex_practice_categories.py tests/test_codex_specialist.py tests/test_ctf_artifacts.py tests/test_ctf_tools.py
```

This is offline adapter coverage, not a model-solving benchmark or an official
flag-verification test. The fixtures are synthetic; they do not exercise live
web endpoints, challenge executables, or platform submission.

## Focused orchestration evidence (2026-11-17)

Executed on the current `codex/ctf-readiness` checkout:

```text
$ .venv/bin/python -m pytest -ra tests/test_codex_practice_categories.py tests/test_agent_orchestration.py tests/test_ctf_orchestration.py
............................                                             [100%]
28 passed in 1.22s
$ .venv/bin/ruff check tests/test_codex_practice_categories.py
All checks passed!
```

The six newly parameterized assertions validate each typed specialist profile
and its no-submit/no-scope-expansion/no-credential/no-delegation permissions.
The run also verifies deterministic category fixtures together with routing,
scoped-intent, and orchestration contracts. It remains synthetic integration
evidence; it does not prove model-solving effectiveness or satisfy the broader
benchmark criteria in Issues #4–#8.
