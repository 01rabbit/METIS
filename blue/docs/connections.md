# Connections

Profiles are data owned by the operator, never generated from an untrusted ticket. Copy the
example into ignored `.state/connections.json`. Targets are explicit; no discovery or scanning
is performed. Every connection declares a finite `resource` known to the owner scheduler.

| Protocol | Adapter | Read behavior | Mutation grant |
| --- | --- | --- | --- |
| SSH | OpenSSH, optional sshpass | system / identity / processes / sockets / os-release / allowlisted read-log | Arbitrary remote commands are not exposed |
| VNC | TigerVNC viewer | `view` with ViewOnly | `control` |
| RDP | FreeRDP client | Interactive session; no guaranteed read-only mode | `open` |
| SOCKS | OpenSSH dynamic forwarding | Loopback-only proxy, usable by scoped clients | `start` |
| VPN | OpenVPN | Operator-provided profile | `start` |
| Browser | Native browser connector | `view` returns the scoped URL and contract | Application writes require an owner grant in the native workflow |

Preview a connection without executing:

```bash
metis blue connect evidence-host --action system --profiles examples/connections.json
```

Execution requires an existing running task holding its resource lease:

```bash
metis blue connect evidence-host --action system --execute --run RUN_ID --task TASK_ID
```

When a write has already been authorized, the owner issues a specific grant and delegates it:

```bash
metis blue grant RUN_ID TASK_ID --resource analysis-vm --action open \
  --reason 'User authorized this remote desktop session for the incident' --ttl 300 --uses 1
metis blue connect desktop-rdp --action open --execute \
  --run RUN_ID --task TASK_ID --grant GRANT_ID
```

Do not put the owner capability in a worker prompt. The native owner invokes the broker on the
worker's behalf. For SSH password authentication, a profile may name `password_env`; the
value is passed to sshpass in its child environment, not argv or logs. For VNC, use a private
password file. RDP accepts `password_env` and sends that value over stdin using FreeRDP's
`/from-stdin:force`; it never adds `/p:password` to a command. Otherwise use the client's UI.
`certificate_sha256` adds a separately verified server certificate to FreeRDP's fingerprint
allowlist. Normal trusted-CA verification still applies; this is not exclusive certificate
pinning. Without an allowlisted fingerprint, untrusted certificates are rejected. SHA256
fingerprints are normalized for FreeRDP 2/3 compatibility. SSH accepts `known_hosts_file`;
VNC accepts `ca_file` for X509Vnc and disables both clipboard directions.
Remote host-key and certificate checks must remain enabled. Initial host-key enrollment is an
operator configuration step; verify its fingerprint through an independent source.

The runner does not install clients or request sudo automatically. A VPN profile is sensitive
and may contain certificates, private keys or active directives: review it before use. Run
privileged networking in a dedicated namespace or VM with operator-configured egress rules.
A `start` grant authorizes the profile operation, not unrelated network writes through it.
Stop the connection before releasing its resource. `--timeout` bounds foreground processes
and terminates the complete process group. CLI timeouts and client failures return exit code 2.
Profiles with daemonization, nested configs, plugins, script hooks or unmanaged logging are
rejected; this is a lifecycle constraint, not a general sandbox for arbitrary VPN profiles.

Python workers can keep a desktop or tunnel alive while they use it:

```python
from metis.blue.connections import ConnectionSession
from metis.blue.ledger import ConnectionLedger

store = ConnectionLedger(Path('.metis-state/metis.sqlite'))  # Daybreak: metis lease task / metis permit issue
with ConnectionSession(store, run_id, task_id, vpn_profile, 'start', permit_id) as connection:
    connection.wait_for('Initialization Sequence Completed', timeout=30)
    # Use the approved evidence service through this network namespace.
# The process group has stopped before the context returns.
```

SQLite registers a connection before launching it, atomically checks its lease and consumes
the scoped grant. A task cannot finish while one of its registered clients is active, and
simultaneous connections cannot exceed that task's leased units. A killed supervisor leaves
an active record for owner reconciliation. Do not clear it until the recorded process group
has been confirmed stopped; there is no time-based automatic release.

GUI automation and external connectors are provided by Codex/Claude and the local environment;
METIS supplies the profiles, lease/grant checks and operating contract. CLI analysis workers have
no generic remote shell or GUI mutation tool. Use native workers and the owner broker for those
operations. A successful profile preview is not a live connectivity test.

## Disposable integration lab

```bash
python3 scripts/connection_lab.py
```

This builds a Docker image containing the real clients and creates disposable SSH, xrdp,
X509Vnc and OpenVPN servers. It generates fresh SSH keys, a short-lived CA, certificates and
passwords. An internal Docker network has no published host ports. OpenVPN changes only the
client/server container network namespaces, using NET_ADMIN and `/dev/net/tun`; the host's
routes and DNS remain unchanged. Docker must already be available.

Tests verify SSH login and host-key rejection; a real RDP desktop frame and bad-certificate
rejection; an encrypted VNC frame; an HTTP fixture through SOCKS; a mutually authenticated
OpenVPN tunnel carrying HTTP; wrong VPN server identity rejection; grant denial and refusal
to release active leases. Screenshots, versions, SQLite reports and generated credentials
are initially copied to ignored `.state/connection-lab/<id>/`. Test containers, networks and volumes are
removed in a finally block. After `compose down` returns success, the runner removes the nine
known generated private-key/password files while retaining results, screenshots, logs, public
certificates and configuration. `cleanup.json` records the shutdown result, removed filenames
and any deletion failures. If shutdown fails, times out or cannot be confirmed, credentials
remain private for owner reconciliation; no secret deletion is attempted. An unknown directory
or a deletion error is reported as a cleanup failure, never as successful removal. This is
scoped file removal, not secure erasure or a scan for secrets in logs or backups. Earlier lab
runs require a separate confirmed-stop cleanup. Inspect `cleanup.json` before treating cleanup
as complete. The built image is retained for the next run. Use `--skip-build` only after
confirming that image matches the current source; the flag does not verify that match.

The clients are native OpenSSH, FreeRDP, TigerVNC and OpenVPN, wrapped by METIS's authentication,
permission, process and resource handling. The integration image supplies Linux dependencies;
direct `metis connect` on the host requires those client binaries in PATH. Lab testing does not
establish compatibility with every Windows domain, gateway or enterprise VPN configuration.

References: [OpenSSH client](https://man.openbsd.org/ssh),
[TigerVNC viewer](https://tigervnc.org/doc/vncviewer.html),
[FreeRDP command-line interface](https://github.com/FreeRDP/FreeRDP/wiki/CommandLineInterface),
[OpenVPN manual](https://openvpn.net/community-docs/community-articles/openvpn-2-6-manual.html).
