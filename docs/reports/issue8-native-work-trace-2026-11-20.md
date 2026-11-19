# Issue #8 pinned llama.cpp work trace

## Scope

This change adds a separate test-only CPU build of llama.cpp at source commit
`b1b770d90d94cad9e9ea5b993bdbc383a522fb28`. It emits aggregate counters for
`llama_process`, encode/decode calls, graph dispatches, graph positions,
pre-dispatch and graph failures, and server batch retries. Prompts, generated
text, and raw server logs are not retained in the result. The registered public
fixture is `stories260K.gguf`, SHA-256
`270cba1bd5109f42d03350f60406024560464db173c0e387d91f0426d3bd256d`.

The patch SHA-256 is
`7b4e755bd13a2cc2505fb6147dd066de682da2b6e1aa6ff9715b68238a62123d`; the
locally built binary SHA-256 was
`feeaae916f0aaba2770bb326a05a0865fb1186aa5de716f8ef2c9b1e0d39f6d2`. The
manifest identifies those artifact digests and the declared source pin. The
manifest alone is not a signed or independent proof that an arbitrary binary
was built from that source; the reported observation came from the checked
fresh-checkout build procedure.

## Observed local probes

On Darwin arm64, the fixed prompt returned HTTP 200, 20 evaluated positions,
and 3 predicted positions. Startup recorded one process call and 2 graph
positions. The request recorded 3 process calls, 3 graph dispatches, and 22
graph positions.

With the test-only retry switch, the same request returned the same response
counts. The request trace recorded 4 process calls, one failed process call,
one injected precompute refusal, and one server batch retry. It still recorded
3 graph dispatches and 22 graph positions. The injection returns before graph
submission; this exercises retry-loop control flow, not genuine KV-capacity or
allocator failure behavior.

## Validation

- The pinned CPU-only `llama-server` build completed from a fresh source tree.
- Normal and injected-retry fixture probes completed and their aggregate
  records passed the strict parser.
- `tests/test_native_work_trace.py`: 14 passed, including patch pin mismatch,
  inconsistent retry counters, duplicate JSON keys, and OS-level 4 MiB log-file
  limit checks.
- Ruff, mypy, `scripts/check_repo.py`, `sh -n scripts/build_llama_work_trace.sh`,
  and `git diff --check` passed.

## Limits

These are single-profile local observations. The synthetic refusal is not a
real backend failure. Hashing and later execution/model loading are path-based,
so a concurrent same-user replacement between those steps is not excluded.
The probe does not establish a provider or token ceiling, held-out eligibility,
real CTF solving, MUNIN benefit, or any Issue #8 acceptance criterion. The hard
token-budget capability flags remain false. No official challenge endpoint or
verifier was contacted.
