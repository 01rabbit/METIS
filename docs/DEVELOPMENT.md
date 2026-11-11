# Development and current CLI

Use the existing isolated checkout; create no Git worktree unless requested.
Python 3.12 or later is required.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]' build
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

Without that variable, six container cases are explicitly skipped. CI supplies
it and pulls the pinned image. The runner uses the local Unix daemon explicitly;
no remote Docker endpoint, host filesystem mounts or arbitrary tools are accepted.
It supports only Base64 decoding, hex decoding and SHA-256 for local fixtures.
This is not a general-purpose hostile-binary runtime.

The project does not yet have a dependency lockfile. These commands honor the
declared version ranges; they do not promise identical future resolutions.

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
