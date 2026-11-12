# ADR 0005 — Codex is the model host

The user clarified that the product is to run inside Codex and does not need a
second model API or a mandatory Docker service. The current Codex agent supplies
reasoning, reads the problem, chooses bounded tools and submits a candidate.
The repository skill and `metis codex` command implement that interface.

The native backend handles only three bounded builtin data transforms. It never
executes problem text, uploaded binaries, arbitrary Python/shell or network tools.
Its input/output are bounded by 64 KiB and each transform has linear work and
bounded memory. This is a distinct trusted data-tool interface; it does not
disable the Docker runner's guards or permit untrusted host code execution.

Generated demos retain only an SHA-256 answer commitment, never plaintext hidden
answers. The commitment is created before solving and checked by the controller.
No commitment means no verified verdict. Codex receives tool observations; event
logs retain metadata only. Session context persists across CLI invocations.
The host/database owner can tamper with a commitment: this is a local workflow,
not a technical isolation boundary against the Codex agent itself or a protected
held-out evaluator. Existing standalone experiments remain optional.

Default push/PR checks need no Docker. The separate manually triggered
`standalone.yml` workflow retains strict resource checks for that optional backend.
