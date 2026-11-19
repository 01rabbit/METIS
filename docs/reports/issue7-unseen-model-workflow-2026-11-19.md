# Issue #7 unseen local model workflow pilot

Two fresh random instances of known benign encoding families were generated
locally, one from each family. The real Codex CLI received only encoded bytes and a fixed
JSON schema. The private oracle commitment stayed in controller memory and
was not passed to the model or stored in run events. The model selected
base32 then base64 for one fixture, and base64 then hex for the other.

The first pilot used the legacy replay path, which persisted decoded output as
an untrusted derived artifact. That path is unsuitable for private-answer
trials. Its private database and generated artifact roots were deleted. The
result below comes from a new digest-only replay: the sandbox emits only
length and SHA-256, and the controller creates no derived artifact. Inspection
of both run artifact roots found no `.metis-derived` files.

Environment: macOS arm64, Python 3.12, local Docker image
`sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b`,
`linux/arm64`; Codex CLI invoked in ephemeral, read-only, structured-output
mode with the existing specialist Seatbelt isolation, disabled web and tool
features, and an allowlisted model API proxy. Captured diagnostic output was
capped at 64 KiB. No challenge executable ran on the host. METIS performed all transforms
in its no-network, no-host-mount sandbox.

Observed command (private database and seeds remain outside Git):

```sh
PYTHONPATH=src python scripts/issue7_unseen_trial.py \
  --database /tmp/metis-issue7-private-retest.sqlite \
  --image sha256:6c21b45c2c80dd4422b464b4b666f3c7912a19205f80eb0c2a59c17bf088c36b \
  --platform linux/arm64
```

Both fixtures returned `ok=true`, `reproducible=true`, and
`oracle_match=true`. Run IDs: `a70e6c77b4b34067b22ca908cd71172e`,
`5a3399f68fee42aca31df63ce65e9b14`. No answer or digest is in this report.
This is a two-case local demonstration, not a held-out benchmark. Issue #6's
measured-gain dependency remains unmet; Issue #7 stays open.
