# Threat model (initial)

Protected assets: host credentials and home data, internal networks, competition scope, hidden oracle flags, cost budgets, execution evidence and MUNIN records.

Attackers and hostile inputs: uploaded executables, archives, puzzle text, retrieved writeups, supply-chain dependencies, challenge network services and model-generated tool requests.

Key trust boundaries: user-to-manifest, LLM-to-tool broker, broker-to-container/VM, sandbox-to-network, solver-to-verifier, training-to-held-out evaluation, memory-to-planner, API-to-operator.

Controls to implement and test: explicit grant/scope, no network by default, endpoint allowlisting, no privileged runner, filesystem read/write allowlists, fixed CPU/memory/pid/time limits, safe archive extraction, checksum recorded, structured tool argument validation, secret redaction, hard global budget/cancellation, oracle isolation, immutable event stream and narrowly scoped tool credentials.

Threat scenarios: tool output prompt injection; malicious symlink or zip traversal; DNS rebinding; infinite tool loop; evaluation contamination; compromised container; agent attempting to rewrite own policy; flag spoofing through regex; malicious retriever memory; cost exhaustion. Treat every one as an adversarial test case.

Host threat assumption: a standard Docker container is not a proven boundary against hostile kernel-level exploits. Consider disposable Linux VM isolation for untrusted binaries, especially on macOS.

## Implemented controls for dynamic execution and live services (2026-11)

- `metis sandbox`: challenge programs run only in a fresh container per call:
  `--network=none`, `--read-only`, `--cap-drop=ALL`, `no-new-privileges`,
  user 65534, PID/memory/CPU limits, tmpfs `/work`, `--pull=never`, an immutable
  image ID or digest, and no bind mounts (inputs are streamed over stdin).
  Remote Docker daemons (`DOCKER_HOST=tcp|ssh`) are ignored. Docker Desktop and
  similar tools on macOS add a VM boundary; a container alone remains defense in
  depth against kernel exploits.
- `metis remote`: statement-derived `nc` endpoints are suggestions only. A
  grant binds host, port and TLS to a run (max eight). Hostnames that resolve
  to non-global addresses are refused (DNS rebinding); literal IPs are explicit
  grants. TLS verification is always on. Exchanges are bounded (60 s, 1 MiB,
  256 steps); solver pipes are bounded (900 s, 16 MiB each way), strip
  credential-like environment variables, and refuse paths inside the challenge
  snapshot. Events record digests, not received bytes.
- `metis web open --render`: Playwright routes abort every request outside the
  granted origins, downloads are disabled, service workers are blocked, and the
  final URL must stay in scope.

### Proxy-aware egress, HTTP interaction and SSH (2026-11-13)

- Raw TCP (`metis remote`) tunnels through `ALL_PROXY` (SOCKS5, remote DNS) or
  `HTTPS_PROXY` (HTTP CONNECT) unless `NO_PROXY` matches. The proxy then owns
  DNS and destination policy, as it already did for HTTP; METIS never bypasses
  it. Local private-address checks still apply to direct connections.
- `metis web request` reaches only origins granted for the run (`metis web
  grant`, a Daybreak action). Arbitrary request headers are allowed except
  hop-by-hop/framing headers; `Authorization` and `Cookie` cannot be set for
  the platform origin, the platform token is attached only to the platform
  origin, and platform cookies are never returned.
- `metis remote ssh` uses paramiko over the same scoped socket, pins the host
  key per run on first use, accepts the password on stdin or from an
  environment variable, never stores it, and saves downloaded files as run
  artifacts (8 MiB each, at most eight per call).
- Budgets: the wall clock starts at the first action. `metis codex extend` is
  the only way out of `exhausted`, only for a budget stop, with hard ceilings
  (2000 actions, 7 days).
