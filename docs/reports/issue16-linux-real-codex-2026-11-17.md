# Issue #16: Linux real-Codex isolation verification (2026-11-17)

## Environment and credential handling

- Colima `rosetta` VM: Ubuntu 24.04, aarch64, 4 CPUs, about 6 GiB RAM, cgroup v2.
- Tested Linux arm64 Codex CLI 0.166.0 and 0.169.0. METIS ran from a temporary Linux venv; the CLI binaries and bubblewrap were unpacked under `/tmp`.
- The existing hardware-key-authenticated `auth.json` was copied into a mode-0700 temporary `CODEX_HOME`; the file was mode 0600. The test did not access a challenge, submit a candidate, or pass credentials to CI or the challenge sandbox. Both probes reported auth `unchanged`. Temporary files were removed after the test.

## Results

For both versions, `metis agent codex-probe --ping --allow-untested-codex ...` returned `ready: true`:

| Check | 0.166.0 | 0.169.0 |
| --- | --- | --- |
| Real isolated ping | return code 0 | return code 0 |
| bwrap file read/list/write outside turn | denied | denied |
| turn-directory write | allowed | allowed |
| direct network and non-allowlisted proxy destination | denied | denied |
| NoNewPrivs, OS child process | set / denied | set / denied |
| thread creation | allowed | allowed |
| configured spawn canary without `--ephemeral` | refused | refused |
| refusal evidence | `code-mode host is disabled` | `code-mode host is disabled` |
| METIS detection | `sub_agent_attempt` | `sub_agent_attempt` |

The Codex tool name remains visible to the model. The refusal comes from the tested CLI configuration (`agents.enabled=false`, MultiAgentV2 disabled, and a one-thread cap), not from seccomp. METIS now omits `--ephemeral`; router refusal text is classified as a spawn attempt and ends the specialist attempt with a policy violation.

## Negative control

On 0.169.0, a bounded control run removed `--ephemeral` and the agent-disable settings. `collaboration.spawn_agent` succeeded and its one-line child task returned `HELLO`. This confirms that seccomp alone does not block Codex's in-process collaboration tool and that the configured refusal is meaningful. The control did not use challenge data or execute challenge code.

## Gate assessment

- Spawn is not hidden. Under both currently allow-listed versions, the configured call is refused without `--ephemeral` and the refusal is detected. This satisfies the issue's alternative of reliable call refusal for the tested versions.
- OS file isolation and version fail-closed tests remain covered by the local and CI test suites. Unsupported Windows has no backend and fails closed; no Windows isolation guarantee is claimed.
- A future Codex version must pass `codex-probe --ping` before it is added to `TESTED_CODEX_VERSIONS`. The successful negative control is why the version gate remains necessary.

Commands and code references: `.venv/bin/pytest -q tests/test_codex_isolation.py tests/test_codex_specialist.py`; `metis agent codex-probe --ping`; `src/metis/core/codex_isolation.py`; `src/metis/core/codex_specialist.py`.
