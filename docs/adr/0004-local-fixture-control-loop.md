# ADR 0004 — Local-fixture control loop and independent verification

Status: Accepted for local baseline development; real-model P1 gate is unpassed.

The solver sees only an immutable validated manifest and bounded observations.
It proposes one typed tool/candidate/halt decision at a time. The controller owns
authorization, budgets, state transitions, runtime selection and verification.
No model decision can change the tool set, image, oracle path, grant or budgets.
Tool/candidate text and exception messages are omitted from persistent evidence.

FixtureOracle is a controller-owned component holding a private external answer
mapping. It returns a boolean using constant-time byte comparison. The provider
receives neither its object, path nor contents. The actual tool process runs in
the restricted Docker boundary tested in ADR 0003. Controller compromise is
outside this boundary; a malicious in-process Python adapter would invalidate it.
Only trusted adapters and the external model's structured messages are supported.

FixtureProvider is an explicitly deterministic baseline. Synthetic crypto and
misc puzzles validate integration without passing evaluation answers to the
solver. Failed transforms can cause a distinct next action; exact repeats stop.
These fixed trials are not evidence of unknown-problem ability or improvement.

OpenAIProvider is optional and uses a fixed HTTPS destination with redirects
denied. It has bounded input/output, output-token limits and a timeout. Calls
reserve token maxima and an operator-configured conservative charge ceiling
before sending. No refunds are assumed for failed calls. The ceiling depends on
correct current pricing and is not verified actual billing. No paid request has
been made during this implementation.

Cancellation markers are checked between calls; Ctrl-C is handled during active
workers. Per-call and global deadlines stop subsequent work; cleanup can add at
most five seconds. A Docker creation timeout/interrupt is an unknown daemon
outcome, not a successful cancellation. It is surfaced as infrastructure failure.
Durable events support inspection/replay, not execution resume. A protected
network verifier protocol, resumed model state and general isolated tool support
remain future work. These are limitations, not features claimed by this change.

Environment finding: Docker info reports rootless mode, cgroup version 2, but
driver `none`. Requested quota flags alone are not evidence of enforcement.
The runner now rejects that capability state before starting a container and
also checks actual memory.max/pids.max/cpu.max inside every worker. Current
container acceptance tests are blocked; CI requires them on a capable daemon.
No privileged replacement daemon or weaker fallback is introduced.
