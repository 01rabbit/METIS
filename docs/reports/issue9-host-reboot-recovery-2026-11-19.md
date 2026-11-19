# Issue #9: disposable Mac host reboot recovery (2026-11-19)

## Scope and setup

An authorized local drill used a dedicated Colima `linux/arm64` profile, a
private SQLite database and artifact root, the pinned sandbox image
`sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b`,
and a harmless sleeping script. The sandbox worker had no network or host
mounts. The source checkout was pinned at `155b70fdbbe8cdb2c3c92db29ce49eff654685ff`.
No credential, challenge executable, answer, or official submission was used.
Colima provisioning itself was not proven offline.

## Observations

The first attempt was **inconclusive**. Its one worker reached the product's
300-second per-action timeout and returned the run to `planning` at 20:30:40
JST; the Mac did not boot again until 20:33:42 JST. The changed boot UUID alone
therefore did not demonstrate interruption of an active worker. Its separate
evidence was retained and its disposable VM removed.

The second attempt chained bounded 300-second actions without changing the
product timeout. The Mac boot UUID changed from
`94105958-39F9-4E7C-877C-FAC7517047D7` to
`0A3B345E-795D-4591-9C1C-D3C987F00344`. The initial worker named by the
pre-reboot `arm` check expired at 20:52:16 JST. The next worker and active
operation were recorded in SQLite at 20:52:16 JST, before the host boot time
of 20:52:39 JST. The audit chain contained an `executing` event for this second
action, with no completion event before reboot.

After the host reboot, the run was still `executing` with 28 of 30 actions
remaining; both actions had been charged. The dedicated VM restarted, and
Docker reported no surviving worker container. The first
`metis codex recover` returned `planning` and `worker_teardown=confirmed`.
The second returned `planning` and `worker_teardown=not_running`; 28 actions
remained. Reading the run event chain found no `solved` event. The dedicated
VM and disposable state were removed after private evidence was copied and
SHA-256 checked.

The prepared script's stricter condition required the worker named by
`arm` to match the worker persisted after reboot. That condition **failed**
because the first bounded action expired and a successor started before the
host restarted. The script recorded this as inconclusive and did not run its
automatic recovery. The observed recovery above was performed manually on
the successor worker after a read-only pre-recovery SQLite snapshot. The
result demonstrates recovery of a persisted active run after an actual host
reboot, with the specific timing limitation that the successor was established
by the SQLite and audit timestamps rather than a second pre-reboot `arm` check.

The private evidence archive is at
`/Users/mao/Library/Application Support/METIS/issue9-reboot-drill/issue9-reboot-evidence-2026-11-19.tar.gz`
with SHA-256
`afbc56a521547089990d5f93188aca3dd48fedc938b00c694b81c4c5045249bd`.
It contains the first inconclusive attempt, the second attempt's pre-recovery
snapshot and post-recovery record. The archive is outside Git and available
only to reviewers with access to this machine.

This is one disposable host-reboot recovery observation. It does not prove
production recovery, credential retention or revocation, signed release
provenance, the Issue #7 dependency, or the full Issue #9 acceptance gate.
Issue #9 remains open.
