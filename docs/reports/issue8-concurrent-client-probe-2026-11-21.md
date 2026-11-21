# Issue #8 concurrent-client probe — 2026-11-21

## Result

The pinned native `llama-server` smoke completed successfully in an Ubuntu 24.04 `linux/arm64` container under Colima's `rosetta` profile. Existing startup, prompt, decode, receipt, socket, and kill/recovery cases passed. The added case released two client threads together against a server started at the exact cap. It observed the cap-denial terminal receipt with `charged == cap`; zero or one client returned a valid completion.

This launch fixes `--parallel 1`. Server requests queue, so this probe does not demonstrate overlapping server-side decoding and is not concurrency-safety qualification. The denied request terminates the process; the other client may also disconnect. This is limited to the pinned model fixture and target architecture. METIS's strict token/work capability remains disabled.

## Reproduction identity

- Upstream llama.cpp commit: `b1b770d90d94cad9e9ea5b993bdbc383a522fb28`
- Native patch SHA-256: `eef420ec22061350d4b2008eac66e9c5c8ac003d7071eb83d69c547d8ffa8b06`
- Built `llama-server` SHA-256: `ac280d2bf80b4b40c4f715d4044ec01c17677c3b32a7d9763b390b96daad72fe`
- Smoke script SHA-256 at run time: `027dbb7847a0c771aa0d196eb742f0676521c333430c8cd563a0a1f4998cf3ee` (commit `be69374`). The committed `smoke.py` is `dbd7ece12d97eded48872f40aa5be16924deabd4a6cf1a7e347a9c1b8178985b` (commit `872ffc9`); the only change is the wording of the final printed line quoted below. No assertion or request changed, and the smoke was not rerun after that edit.
- `stories260K.gguf` SHA-256: `270cba1bd5109f42d03350f60406024560464db173c0e387d91f0426d3bd256d`
- Output: `Verified work receipts on Unix socket shutdown and denial at prompt/decode cap 22`; `Verified simultaneous client arrivals at cap; denial receipt charged the full cap` (the committed script now prints `Verified two client threads released together at cap; denial receipt charged the full cap`); all remaining smoke cases passed.

The source patch, smoke script, and fixture digest are committed in this repository. The built executable and downloaded model were temporary local artifacts; their hashes were recorded, and both were removed after the probe.
