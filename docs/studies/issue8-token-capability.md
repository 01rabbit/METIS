# Held-out token admission gate

The 2026-11-19 exploratory Rev study exceeded its declared 50,000-token cap
in every run. Its Codex CLI runner reports provider usage after a turn, while
the tested CLI interface does not provide a verified bound on both input and
output tokens before dispatch. A post-turn check cannot make the earlier call
fit within the cap.

Real-model held-out runs with a bound prompt now refuse specialist execution
unless the supplied runner explicitly provides hard token-budget enforcement.
`CodexCLI` declares this capability unavailable. This is a fail-closed gate,
not a claim that a working token-controlled runner exists. Synthetic test
runners can declare the capability to exercise the remaining arm-attestation
path, but such tests are not real-model benchmark evidence.

The next study stays on hold until an authorized runner can prove per-call
input and output limits, reserve aggregate tokens atomically across parallel
specialists, reconcile reported usage and interruption, and reject missing
usage. A new protocol must be registered before any new comparison calls.
No separate model API credential is requested by this change.

## Native fixture build identity v2

The pinned native fixture manifest now records a bounded, canonical hash list
for the executable's recursively declared Linux ELF `DT_NEEDED` dependencies
and its `PT_INTERP` loader. The build and pre-launch checks inspect ELF
metadata with `readelf` and the local `ldconfig` cache; they do not run
`llama-server`. Runtime preflight re-resolves the closure and verifies each
file before consuming the launch claim. Missing or ambiguous loader-cache
entries, non-matching ELF architecture, oversized output, RPATH/RUNPATH,
FILTER/AUXILIARY/AUDIT/DEPAUDIT tags, and unsupported targets fail closed.
Only glibc Linux `aarch64` and `x86_64` hosts with the accepted GNU `readelf`
and `ldconfig -p` metadata formats are supported by this manifest version.
Musl/Alpine, other libc implementations, unexpected tool paths/output formats,
and Mach-O/Darwin native launch are intentionally refused until their loader
rules can be verified with equivalent evidence. The resolver requires one
unique loader-cache path for every declared dependency; it does not emulate
glibc's fallback search paths or hardware-capability selection. A present
`/etc/ld.so.preload` must be root-owned, not group/world writable, and empty.
The root-owned system `readelf`/`ldconfig` tools, current loader cache, and
trusted OS files are part of the local trust boundary.

This binds the declared ELF dependency closure, not libraries loaded later via
`dlopen` or mutable loader state after preflight. `readelf`, hashing, and the
later host-loader use are path-based rather than bound to one open file
descriptor; a concurrent same-user writer may replace a file between those
steps or before `exec`. This check does not defeat that race. The externally
pinned manifest remains the trust root. This change does not turn the native
work counter into a provider token cap, change the false hard-cap capability
flags, provide an independent CTF oracle, or satisfy the held-out benchmark/gain
gate. No model, provider, or CTF action is part of the build-identity test path.
