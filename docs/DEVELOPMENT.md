# Development and current CLI

Use the existing isolated checkout; create no Git worktree unless requested.
Python 3.12 or later is required. uv 0.13.5 was used for validation.

```sh
uv sync --locked --extra dev --python python3.12
.venv/bin/python -m pytest
.venv/bin/ruff check src tests
.venv/bin/mypy src/metis
.venv/bin/python -m build --outdir /tmp/metis-dist
```

Docker integration tests use a trusted, immutable Python image. Start the local
Docker daemon using the host's supported procedure, then run:

```sh
export METIS_TEST_DOCKER_IMAGE=python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
docker pull "$METIS_TEST_DOCKER_IMAGE"
.venv/bin/python -m pytest
```

Without that variable or enforced cgroup v2 limits, eight container cases are
explicitly skipped. CI supplies the image and `METIS_REQUIRE_DOCKER_TESTS=1`,
which makes missing capabilities a failure. The runner uses the local Unix daemon explicitly;
no remote Docker endpoint, host filesystem mounts or arbitrary tools are accepted.
It supports only Base64 decoding, hex decoding and SHA-256 for local fixtures.
This is not a general-purpose hostile-binary runtime.

Current cloud blocker: the daemon is rootless with `CgroupDriver=none`. CPU,
memory and PID flags cannot be assumed enforced. The runtime now refuses to run
until a cgroup v2 driver and actual in-container limits can be confirmed. Obtain
an environment with delegated/enforced cgroups through platform recovery; do
not start a privileged daemon or weaken this check. Earlier functional decoder
trials were before this check and do not establish resource isolation.

`uv.lock` pins development/runtime dependency resolution. Use `--locked` to avoid
silently changing it. The build backend still follows the declared build-system
range; bit-for-bit reproducible distributions are not claimed.

Validate and prepare an authorized fixture without executing challenge content:

```sh
.venv/bin/metis validate challenges/training/fixture-001.json
mkdir -p runs
.venv/bin/metis prepare challenges/training/fixture-001.json --database runs/local.sqlite
.venv/bin/metis inspect RUN_ID --database runs/local.sqlite
```

Use the returned run ID for inspection. Output is JSONL. The database is
controller-only and must never be mounted into a future solver sandbox.
Only metadata belongs in event details: no credentials, flags or raw tool output.
Run history can be exported by `RunStore.export_jsonl`. Lifecycle replay is
available, but resuming model/tool execution is not implemented.

No model API key is required by these commands. No server is started. A valid
manifest is not proof of artifact safety or solve capability. Use `read_artifact`
for descriptor-based bounded reads with no symlink components; pass copied bytes
to the runtime. Archive extraction and hostile executable support are absent.

CI definitions run the same checks, but local passes are not evidence of a
successful GitHub Actions run. macOS controller support requires an actual
macOS test run; Linux validation alone does not establish that support.

## Bounded local-fixture run

Create a new external private answer store and generated challenge directory;
use paths outside the source checkout for both. Never commit the private store.
Replace `/tmp/metis-demo` with a fresh directory if it already contains an oracle:

```sh
mkdir -p /tmp/metis-demo
.venv/bin/metis generate-fixtures /tmp/metis-demo/challenges --oracle /tmp/metis-demo/private/answers.json
.venv/bin/metis run /tmp/metis-demo/challenges/GENERATED_ID.json --database /tmp/metis-demo/runs.sqlite --oracle /tmp/metis-demo/private/answers.json --image "$METIS_TEST_DOCKER_IMAGE" --provider fixture
```

The generator prints manifest paths, never hidden answers. Use a returned path
for `GENERATED_ID.json`. The fixture provider is a deterministic local baseline,
not an LLM. Crypto starts with an intentionally invalid transform, then tries a
different tool. The controller verifies candidates using a separate host-only
oracle component; no answer file/path is passed to the provider or mounted into
the tool container. Unknown candidates never count as solves.

Runs reject artifacts and network endpoints: this workflow supports inline local
decoder fixtures only. Only the three fixed transforms are available. Model or
tool errors become auditable ERROR/failed observations without exception text.
`--max-actions`, `--wall-time-seconds`, `--per-tool-seconds`, `--max-model-tokens`
and `--max-cost-usd` are controller-owned. Repeated identical tool actions stop.
`--stop-file PATH` checks a controller-owned marker between calls. Ctrl-C during
an active worker attempts cleanup; cancellation during creation, a creation
timeout or unconfirmed cleanup is an explicit infrastructure error requiring
inspection. Budget deadlines exclude bounded cleanup (up to 5 seconds).
The fixture runtime enforces per-call deadlines; providers must honor their
timeout argument. Arbitrary untrusted Python provider implementations are not a
supported security boundary. Inspect evidence using the returned run ID.

## Optional OpenAI provider

Use `--provider openai --model MODEL --max-call-cost-usd CEILING` only when
existing API use is authorized. Configure `METIS_OPENAI_API_KEY` securely in
environment settings, restricted to `api.openai.com`; an existing `OPENAI_API_KEY`
also works. No secret values belong in chat, Git, commands or event logs.
The environment draft declares the binding; save/review settings and publish
when ready. Draft saving alone neither injects a key nor publishes an environment.

The adapter uses bounded JSON requests/responses, a fixed HTTPS destination,
inherited proxy/CA trust and no redirects. It receives challenge data and tool
observations, never the oracle store. Model calls reserve conservative input/output
token maxima and the configured per-call cost before sending requests, including
failed requests. Cost fields are **reserved ceilings, not measured billing**;
the operator must set a conservative ceiling from the selected model's current
tariff. No real API call or live-model solve has been validated in this environment.
Live-provider acceptance, durable execution resume and macOS validation remain.
