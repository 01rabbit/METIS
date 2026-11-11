# Threat model (initial)

Protected assets: host credentials and home data, internal networks, competition scope, hidden oracle flags, cost budgets, execution evidence and MUNIN records.

Attackers and hostile inputs: uploaded executables, archives, puzzle text, retrieved writeups, supply-chain dependencies, challenge network services and model-generated tool requests.

Key trust boundaries: user-to-manifest, LLM-to-tool broker, broker-to-container/VM, sandbox-to-network, solver-to-verifier, training-to-held-out evaluation, memory-to-planner, API-to-operator.

Controls to implement and test: explicit grant/scope, no network by default, endpoint allowlisting, no privileged runner, filesystem read/write allowlists, fixed CPU/memory/pid/time limits, safe archive extraction, checksum recorded, structured tool argument validation, secret redaction, hard global budget/cancellation, oracle isolation, immutable event stream and narrowly scoped tool credentials.

Threat scenarios: tool output prompt injection; malicious symlink or zip traversal; DNS rebinding; infinite tool loop; evaluation contamination; compromised container; agent attempting to rewrite own policy; flag spoofing through regex; malicious retriever memory; cost exhaustion. Treat every one as an adversarial test case.

Host threat assumption: a standard Docker container is not a proven boundary against hostile kernel-level exploits. Consider disposable Linux VM isolation for untrusted binaries, especially on macOS.
