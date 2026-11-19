# Issue #7 unseen local model workflow pilot

Two fresh benign encoding fixtures were generated locally, one from each
existing family. The real Codex CLI received only encoded bytes and a fixed
JSON schema. The private oracle commitment stayed in controller memory and
was not passed to the model or stored in run events. The model selected
base32 then base64 for one fixture, and base64 then hex for the other.

Environment: macOS arm64, Python 3.12, local Docker image
`sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b`,
`linux/arm64`; Codex CLI invoked in ephemeral, read-only, structured-output
mode. No challenge executable ran on the host. METIS performed all transforms
in its no-network, no-host-mount sandbox.

Observed command (private database and seeds remain outside Git):

```sh
PYTHONPATH=src python scripts/issue7_unseen_trial.py \
  --database /tmp/metis-issue7-unseen-private.sqlite \
  --image sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b \
  --platform linux/arm64
```

Both fixtures returned `ok=true`, `reproducible=true`, and
`oracle_match=true`. Run IDs: `e84a5087627a496ebdc37f15025b604d`,
`00eaf642f08e45228de964f101b0a2d`. No answer or digest is in this report.
This is a two-case local demonstration, not a held-out benchmark. Issue #6's
measured-gain dependency remains unmet; Issue #7 stays open.
