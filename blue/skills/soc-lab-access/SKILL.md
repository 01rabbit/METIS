---
name: soc-lab-access
description: Use scoped SSH, RDP, VNC, SOCKS, VPN and browser profiles for authorized evidence access while coordinating limited sessions.
---

# Evidence access and connections

Use `docs/connections.md` and `metis blue connect --help`. Profiles live in ignored
`.state/connections.json`; the committed example contains documentation addresses only.

Prefer read-only accounts and native connectors. Request the entire resource lease before
opening a session, then report transport status separately from investigation results.
Password authentication is allowed within scope. Resolve credentials from approved environment
references, a credential store or a private file. Never print them or put them in command arguments.
Workers may authenticate without asking again when read access is already authorized.

SSH exposes bounded read actions. VNC can run in view-only mode. RDP interactive control needs
an owner grant because the client cannot reliably enforce read-only remote application actions.
Browser login and reading are allowed; submissions, configuration changes and uploads are writes.
A pre-existing owner grant is sufficient only for its exact resource, action, task and lifetime.

SOCKS binds to loopback and uses remote name resolution when supported. VPN startup changes
routing and requires a scoped grant. Validate the profile, endpoint, route and DNS before use.
Use a dedicated network namespace/VM and default-deny egress for sensitive evidence collection;
verify that a lost VPN cannot route to the target through another interface. METIS does not claim
to install or enforce a system-wide VPN kill switch. Keep provider model traffic outside that
namespace when possible. Distinguish tunnel health, service reachability and authenticated access.

Bounded SSH commands return evidence without executing arbitrary target code. Do not install
agents, collect RAM, change firewall rules or upload samples without the necessary write grant.
Preserve provenance, collection time and hashes. Analyze malware as data in an isolated workspace.

## Transfer and recovery evidence

A desktop file transfer needs a completion signal tied to that exact job plus content
verification; elapsed time, a stable filename and reported size are insufficient. Preallocated
or sparse output can have the expected length before all content arrives. Keep the session
and its resource lease alive until the transfer outcome is settled, then compare source and
destination digests where possible and run the format's integrity check. A trailing zero
region is a lead for incomplete transfer, not a universal corruption test.

Bind resumed work to the current host/session, input identity and grant. After reconnecting,
recheck route, DNS, remote identity and pending operations. A stale browser tab, terminal
prompt or tunnel process does not prove the same target is still selected. A failed or
unknown write is reconciled before retry, including startup of a remote instance. Do not
start a second instance merely because the first launch did not return a visible response.

Record transfer paths and completion evidence using [live collection fields](../soc-remote-triage/references/live-collection-fields.md). Resolve the actual remote path and local acquisition path before interpreting a collected file.
