# Issue #28: Stay attack feasibility assessment

## Primary-source review

The full primary paper is now accessible: Michael Stay, [A Differential Meet-in-the-Middle Attack on the Zip cipher](https://eprint.iacr.org/2020/983.pdf), ePrint 2020/983. It describes recovery from a two-file Info-ZIP archive when the creation timestamp was known closely enough to recover the `rand` state. A recovered PRNG state is only input to later key-recovery stages; it is not the ZipCrypto key.

The authors report that their differential meet-in-the-middle Stage 1 produced about 2^22 candidates, used a few hundred MB for its table, and took about two minutes on a 2017 MacBook Pro. Stage 2 took about a day on a fast desktop with lots of RAM; the complete GPU run succeeded after about a day and a half. The paper reports about $7K in GPU time. This is a different algorithm and cost profile from the 2001 five-file reduced-known-plaintext attack; do not transfer the 2001 ~2^39 estimate to the 2020 attack.

The authors' [breakzip source repository](https://gitlab.com/pyrofex/breakzip) was inspected read-only at commit `f2e30c525309c7eb60514ecfa42ec58a829d2b22`. It is BSD-3-Clause licensed, but the build is a legacy C++/CUDA project requiring CUDA 10.2 or later and a set of Ubuntu-oriented dependencies. Its published stages use external shard files and GPU execution. The code was not built or run. Reusing it would require a review of the exact archive-specific code path, dependency and license attribution, a controller-owned adapter, and a bounded no-network sandbox design; directly executing its helper scripts on the host would violate METIS's execution boundary.

The target ksnctf #39 archive has seven encrypted members, so the older five-file technique is a separate possible route. Its published work estimate is not a short bounded tool call. The real #39 key has not been recovered.

## METIS boundary and remaining work

The current dynamic sandbox is limited to one CPU, 512 MiB, and at most 300 seconds per request. Those bounds cannot run the full published 2020 GPU workflow. A safe adapter would need a complete verified algorithm, independently generated synthetic vectors, cancellable processing, explicit candidate/time/memory bounds, no network or host mounts, and end-to-end key/CRC verification. Timeout or exhausted bounds must remain inconclusive. No Stay key-recovery operation is advertised.

The synthetic specialist-intent test exercises known-plaintext key recovery, CRC validation across all members, derived decryption, and XOR. Its reduction stage is restricted to the true key2 candidate plus decoys: it exercises the attack worker and intent routing, but not the exhaustive search or Stay attack. The optional slow test covers exhaustive Biham–Kocher search separately.
