# External fixture Docker replay, 2026-11-19

PR #89's external intake was exercised on macOS arm64 with Colima 0.10.3
and Docker Engine 29.5.2. The earlier pilot image was absent in this
profile. The run used the cached `python:3.12-slim-bookworm` image by its
immutable local ID
`sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337`
(`linux/arm64`). This Python image is sufficient for the fixed standard-library
decoders.

The test prepares a fresh benign text payload and wraps it as hex, then
base32, without using the METIS fixture generator. OpenSSL computes the
expected SHA-256 independently of METIS replay. The encoded input and
owner-only commitment file are created before proposal, in a temporary
directory outside Git.

A local Perl stand-in exercises the production proposal path and Seatbelt
profile with an empty auth home and an empty egress allowlist. The stand-in
checks that it received the encoded input on stdin. It emits the two-step
plan only if its attempt to open the oracle's canonical host path receives
`EACCES` or `EPERM`. The test omits the default protected roots so that the
oracle-specific rule is the protection being exercised. A successful proposal
is therefore evidence of an OS-level denial for that file on this macOS host.

METIS replayed base32 then hex twice in Docker with its existing
network-free, no-host-mount configuration. The report returned
`ok=true`, `reproducible=true`, and `oracle_match=true`. The public report,
exported run events, and retained artifacts contained neither decoded text,
the expected digest, nor the oracle path. The artifact directory contained
only the encoded input and validated plan. The sandbox internally computes
the output digest for the controller's equality check.

## Commands and results

From the PR worktree, with the existing Colima default profile initially
stopped:

```sh
colima start default --activate=false
docker --context colima image inspect \
  sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337 \
  --format '{{.Id}} {{.Os}}/{{.Architecture}}'
env DOCKER_CONTEXT=colima \
  METIS_TEST_SANDBOX_IMAGE=sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337 \
  METIS_TEST_SANDBOX_PLATFORM=linux/arm64 PYTHONPATH=src \
  /Users/mao/Developer/GitHub/METIS/.venv/bin/python - <<'PY'
import subprocess
import sys
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory(prefix="metis-issue7-real-replay-") as private:
    subprocess.run([
        sys.executable, "-m", "pytest", "-ra", "--basetemp", str(Path(private) / "pytest"),
        "tests/test_workflow_model_trial.py", "tests/test_ctf_workflow.py",
    ], check=True, timeout=120)
PY
docker --context colima ps -a --filter 'name=metis-sandbox-' --format '{{.ID}} {{.Status}}'
colima stop default
colima list
```

The focused suite reported **57 passed in 2.92s** with no skips. The
container listing was empty afterward. The test's temporary directory was
removed and the existing Colima profile returned to `Stopped`.

This verifies the external fixture intake, macOS proposer isolation and
real Docker replay for one benign encoding fixture. The Linux test uses a
stub proposal and provides Docker replay coverage. Real model proposal
quality and held-out performance remain unmeasured here. No CTF submission
was made. Issue #7 and its Issue #6 dependency remain open.
