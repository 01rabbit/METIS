# Issue #8 Linux/aarch64 native fixture smoke (2026-11-20)

## Observed build and run

The native work-budget patch was built from METIS main snapshot
`353aac716cfb16b0908524b8fa80491807e01644` using upstream llama.cpp commit
`b1b770d90d94cad9e9ea5b993bdbc383a522fb28`. The build ran in an ephemeral
Ubuntu 24.04 `linux/arm64` container under the existing Colima `rosetta`
profile. `docker info --format '{{.ServerVersion}} {{.OSType}} {{.Architecture}}'`
reported Docker 29.5.2, OS `linux`, and architecture `aarch64`; `uname -a`
identified `aarch64` in both the VM and container. The run did not exercise
x86_64 translation. The container image digest was
`sha256:ab18ecc70c55c703eae968948f9f1dbbe662aa8d9badac7c982e6a6237b9d74c`;
the build used Python 3.12.3, CMake 3.28.3, and GCC 13.3.0, using the built-in
CPU backend with dynamic backend loading disabled.

The Docker and `uname` outputs, container image digest, tool versions,
executable digest, and sidecar digest are transcribed from observations made
during the run. Their raw command output and build artifacts were not retained
as separate files after cleanup. The patch digest and fixture digest were
checked against the tracked patch and registered fixture hash, respectively;
these can still be verified from the repository.

The resulting Linux/aarch64 executable SHA-256 was
`fc5b9ca352feab434f046596d4a62209bf59cb109987abd970d840e1643bd3cb`. Its
locally generated build sidecar SHA-256 was
`feecd2e7fc3e856d01eb61f3c87eaf27f6105ab4caf25e84bfe4f9bab8e57afc`; this
sidecar records build observations but was not independently approved as an
executable trust pin. The applied patch SHA-256 was
`eef420ec22061350d4b2008eac66e9c5c8ac003d7071eb83d69c547d8ffa8b06`.

The binary passed
`integrations/llama-server-work-budget/smoke.py` against the registered public
`stories260K.gguf` fixture (SHA-256
`270cba1bd5109f42d03350f60406024560464db173c0e387d91f0426d3bd256d`). The
script's output was:

```text
Verified work receipts on Unix socket shutdown and denial at prompt/decode cap 22.
Verified literal comma path, single Unix listener, and stale/symlink/public paths refused.
Verified broken receipt pipe refusal and missing receipt after a deadline and SIGKILL.
```

The cases include startup denial before model load at cap 1; exact nonce/cap/
charge/reason receipt checks; prompt and next-decode budget denial; deterministic
three-token generation with two additional graph positions; an `XDG_CONFIG_HOME`
configuration that requires an API key being ignored for the controlled launch;
nonprivate-directory, stale-socket, symlink, and comma/quote socket-path
handling; an abandoned receipt pipe; and a SIGSTOP-induced client timeout
followed by SIGKILL with no receipt. The comma/quote socket-path case also
checks that the server logs exactly one listening address, equal to the literal
`unix://` prefix followed by the requested socket path.

## Scope and limits

This is a fixture-specific smoke of one patched native binary. It does not run
METIS's controller admission, shared ledger, or manifest-approval path and does
not independently establish that the build sidecar or executable is trusted.
The test does not qualify alternate or split models, other platforms,
concurrent callers, injected backend failures, provider billing-token limits,
or general production capability. A SIGSTOP-induced client timeout followed by
SIGKILL is not a test of controller deadline handling. No held-out study was
admitted or run; the hard-cap capability flags remain false, and Issue #8
remains open.
