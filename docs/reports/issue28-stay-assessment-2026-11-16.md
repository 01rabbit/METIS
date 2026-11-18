# Issue #28: Stay attack feasibility assessment

## Primary-source review

The full primary paper is now accessible: Michael Stay, [A Differential Meet-in-the-Middle Attack on the Zip cipher](https://eprint.iacr.org/2020/983.pdf), ePrint 2020/983. It describes recovery from a two-file Info-ZIP archive when the creation timestamp was known closely enough to recover the `rand` state. A recovered PRNG state is only input to later key-recovery stages; it is not the ZipCrypto key.

The authors report that their differential meet-in-the-middle Stage 1 produced about 2^22 candidates, used a few hundred MB for its table, and took about two minutes on a 2017 MacBook Pro. Stage 2 took about a day on a fast desktop with lots of RAM; the complete GPU run succeeded after about a day and a half. The paper reports about $7K in GPU time. This is a different algorithm and cost profile from the 2001 five-file reduced-known-plaintext attack; do not transfer the 2001 ~2^39 estimate to the 2020 attack.

The authors' [breakzip source repository](https://gitlab.com/pyrofex/breakzip) was inspected read-only at commit `f2e30c525309c7eb60514ecfa42ec58a829d2b22`. It is BSD-3-Clause licensed, but the build is a legacy C++/CUDA project requiring CUDA 10.2 or later and a set of Ubuntu-oriented dependencies. Its published stages use external shard files and GPU execution. The code was not built or run. Reusing it would require a review of the exact archive-specific code path, dependency and license attribution, a controller-owned adapter, and a bounded no-network sandbox design; directly executing its helper scripts on the host would violate METIS's execution boundary.

The target ksnctf #39 archive has seven encrypted members, so it meets the paper's member-count requirement for the older route. The primary paper, Michael Stay, ["ZIP Attacks with Reduced Known Plaintext"](https://math.ucr.edu/~mike/zipattacks.pdf), section 4, describes recovering the PRNG seed from five files and exploiting the twice-encrypted random headers; it says the files are encrypted consecutively and reports a typical runtime under two hours on a 500 MHz Pentium II. That is a historical measurement for the paper's implementation and assumptions, not a measurement of METIS or this exact seven-member archive. The paper's algorithm is distinct from the 2020 BreakZip differential meet-in-the-middle implementation discussed above. No Stay implementation has been run against an independent vector or this archive, and the real #39 key has not been recovered.

## METIS boundary and remaining work

The standard dynamic sandbox is limited to one CPU and 512 MiB; the dedicated ZipCrypto profile provides four CPUs and 2 GiB, while each current request remains capped at 300 seconds. The standard profile cannot run the published 2020 GPU workflow, and earlier BreakZip CPU probes exceeded 2 GiB during normal stage-one candidate accumulation. These observations do not establish whether a faithful, optimized FSE 2001 CPU implementation would fit the ZipCrypto profile. A safe adapter would need a complete verified algorithm, independently generated synthetic vectors, cancellable processing, explicit candidate/time/memory bounds, no network or host mounts, and end-to-end key/CRC verification. Timeout or exhausted bounds must remain inconclusive. No Stay key-recovery operation is advertised.

## Forward-only Info-ZIP interoperability check (2026-11-18)

To verify the archive metadata interpretation independently of a Stay
implementation, the system Info-ZIP 3.0 (Apple modifications) generated a
synthetic seven-member stored archive. Each test file contained 159 repeated
bytes derived from its member number; all entries used the same synthetic-only
password and had the data-descriptor flag set. METIS decrypted all seven
members with the known password, matched each expected payload and CRC, and
found the two header check bytes matched the DOS time fields for every entry.
The independent `unzip -t` command also validated all seven entries.

This confirms the ordinary ZipCrypto forward/header path and the descriptor
check-byte interpretation for this generator. It is not an independent test of
Stay's inverse key-recovery recurrence, does not validate the #39 archive's
secret key, and does not establish a bounded runtime for the 2001 attack.

The two-pass relation from section 4 was then checked on 10,000 seeded
synthetic key states in
[`tests/test_stay_header_differential.py`](../../tests/test_stay_header_differential.py).
An independent bitwise CRC transition drives a direct two-pass encryption; the
test checks first-byte cancellation and compares the observed second-byte
differential with the derived recurrence. Both focused cases passed in 0.38s.
This validates
that forward relation for synthetic states, not the paper's 23-bit inverse
decomposition, candidate pruning, full key recovery, or target feasibility.

As a separate interoperability check, seven Info-ZIP-generated header pairs
were decrypted twice with CPython 3.12's `zipfile._ZipDecrypter`. For all seven,
the recovered random bytes and initial state made the derived second-byte
differential match the stored ciphertext; METIS also decrypted each synthetic
payload with CRC success, and external `unzip -t` passed. This cross-checks the
forward relation against a separately implemented ZipCrypto decryptor and the
Info-ZIP producer. It still does not test the inverse candidate search or the
actual #39 key.

The relation was also used as a candidate filter over a deliberately reduced
12-bit state subspace. For five synthetic two-byte observations, the filter's
complete survivor set exactly matched direct two-pass enumeration of all 4,096
states. Flipping one observed differential removed the planted state, and the
filtered and direct-oracle survivor sets still agreed. The regression is in
the same test file. Its selected state bits and search space are a toy fixture;
this does not implement Stay's published 23-bit slices/carry pruning or
demonstrate full-key recovery.

## Official distribution re-fetch (2026-11-18)

The user selected the official distribution source. The original run was
rechecked directly through its scoped ksnctf origin:

- `GET https://ksnctf.sweetduet.info/q/39/split_flag.php`: HTTP 200, 836 bytes,
  SHA-256 `42e5078588d89c3506afe87b1b01b1ec868986b2098aedde704485b3675ea529`.
- `GET https://ksnctf.sweetduet.info/q/39/flag.zip`: HTTP 200, 2,353 bytes,
  SHA-256 `ff663a29abc5f0ded2c3456bc731b1b21329eb95914286733c40364624e5d8f5`.

The registered archive still contains seven 159-byte stored, encrypted members
with data descriptors and DOS-time check bytes. The bounded glibc search
matched all seven leaked header bytes and regenerated all seven ten-byte random
sequences from one seed. This confirms the PRNG/header hypothesis for this
distribution. The known plaintext required by the ordinary ZipCrypto attack is
still absent. The specialist review confirmed the remaining algorithmic gap:
the section 4 text provides staged bit guesses and carry filters, but no
complete candidate-lifting implementation is present in METIS, and no
independent synthetic inverse vector exists. The exact Stay attack therefore
remains unimplemented and unverified; no candidate was submitted.

The synthetic specialist-intent test exercises known-plaintext key recovery, CRC validation across all members, derived decryption, and XOR. Its reduction stage is restricted to the true key2 candidate plus decoys: it exercises the attack worker and intent routing, but not the exhaustive search or Stay attack. The optional slow test covers exhaustive Biham–Kocher search separately.

## Clarification: the seed output is Stay's attack input, not a dead end

A fresh primary-source review of section 4 corrects an overbroad reading in the
independent critique recorded during the 2026-11-18 ksnctf #39 wave. The
recovered random header bytes are indeed *not* Biham–Kocher known plaintext for
the final stored stream. Stay's section 4 attack is specifically designed for
this case: Info-ZIP encrypts the random header once, reinitializes with the
same password state, and encrypts the header again. The first-byte outputs
cancel; known PRNG bytes then give XOR constraints between the first and second
pass stream bytes. The paper's multi-file divide-and-conquer stages use those
constraints across at least five consecutively encrypted files. The official
archive has seven encrypted files and the seed search matched all seven
leaked header bytes, so the input assumptions appear to match. This is a
strongly supported applicability inference, not proof of a recovered key.

The missing step is the inverse search from those constraints through the
paper's 23-bit guesses, carry filters, candidate lifting, and cross-file
stages. Existing METIS tests verify forward two-pass relations and a toy
reduced state space only; they do not implement or test that staged inverse
algorithm. The independent follow-up critique was right that seed fit alone
is not a key-recovery verdict, but its wording should not be read to exclude
Stay's attack. No full search or official submission has occurred.

The registered official-distribution evidence for the new wave includes
complete source inspection (sequence 105) and full ZIP structure accounting
(sequence 113). The wave found independent random share generation in PHP and
no extra unencrypted archive payload; that eliminates alternate plaintext
routes, not the Stay section 4 route.

## Independent header-compatibility audit (2026-11-18)

A fresh bounded archive inspection recorded seven traditional encrypted,
stored entries and their 12-byte headers (events 141 and 145). The glibc
Info-ZIP seed search recorded seven of seven leaked first-byte matches and
reconstructed the ten PRNG bytes per entry (event 149). This is strong
compatibility evidence for the PRNG/header mechanism; the current search returns
the first matching seed and does not enumerate every possible match.

An independent byte-1 necessary-condition check found that the seven residuals
`C[1] XOR r[1]` are distinct and the 21 pairwise `r[0]` XOR values are all
distinct. Under the stated Stay relation, this excludes only the zero initial
stream-byte value and those 21 pairwise values; it neither proves nor disproves
that one complete ZipCrypto state satisfies all seven headers. The independent
review therefore recommends a joint state-consistency validator with a known
positive Info-ZIP vector and a wrong-seed negative control. A surviving state
would support attack applicability, not recover the keys or validate plaintext.

The official archive remains unbroken. The inverse state search, member CRC
validation with recovered keys, XOR reconstruction, and official verifier
response are still absent; no candidate was submitted.

The current test addition uses the repository's seven-member synthetic Info-ZIP
fixture and its known test password to check the derived second-byte relation
for all seven observations under one initial state. It explicitly checks the
first-byte cancellation too. A negative fixture preserves every first byte but
flips each second PRNG observation, which the relation rejects; one arbitrary
different PRNG seed is also rejected. This is a forward predicate check with a
known state, not a full header parser, an unknown-state search, or a test that
eliminates all alternate seeds passing the first-byte prefilter. It provides no
evidence of target key recovery.

## Naive bit-vector solver feasibility probe (2026-11-18)

As a separate algorithm-selection check, a temporary SMT-LIB model encoded the
ZipCrypto state recurrence and the full double-encrypted ten-byte header plus
two CRC bytes for two independently generated synthetic members. The unknowns
were only the three 32-bit initial cipher words; both members used one planted
state, and their random bytes, CRCs, and ciphertexts were generated locally.
The formula was 175,282 bytes. Z3 4.15.4 returned `unknown` at its 60-second
timeout without a model. An earlier expression-tree generator expanded
recurrences exponentially; that process was stopped before it reached the
solver and no result from it was used.

This is not an attack attempt against #39 and gives no evidence about a tuned
SAT encoding or the published staged attack. It does show that a direct
bit-vector transcription is not an immediately usable substitute for Stay's
23-bit decomposition and carry-pruned candidate-lifting stages. No formula,
synthetic state, or target-derived candidate is retained in the repository.

## Stay key1 candidate-lifting primitive (2026-11-18)

Section 3's multiplication decomposition now has a concrete reduced-width
implementation. Let `P = key1_0 * 0x08088405 mod 2^32` and, for each observed
header transition, let `a` be the known low byte of the updated `key0` and
`q = a * 0x08088405 + 1`. The observed top byte of `key1_1` and a guessed
carry from `P_low24 + q_low24` determine `P_high8` and an inclusive interval
for `P_low24`. Multiple observations must agree on the same high byte and
their carry intervals intersect. Candidate `key1_0` values are lifted from
that product interval with the modular inverse of the odd ZipCrypto
multiplier. This follows the decomposition and carry-bound description in
[Stay's section 3](https://math.ucr.edu/~mike/zipattacks.pdf).

`_stay_key1_product_interval` and `_stay_lift_key1_candidates` implement this
primitive. The focused test reduces the word to 16 bits, generates 100 planted
states, and compares the complete lifted set against direct exhaustive
enumeration with all observed top bytes and carry guesses. The six tests in
`tests/test_stay_header_differential.py` passed; Ruff and mypy passed for the
changed source and test. This validates only this arithmetic primitive. The
full 23-bit/40-bit first stage, its stream-byte and preimage-table candidate
generation, later stages, full-key CRC/decryption checks, sandbox runtime,
and target key recovery remain unimplemented or unverified. Issue #28 and
ksnctf #39 remain open.

The first-stage one-member filter has also been transcribed as
`_stay_predict_second_byte_difference`. Given guesses for the first stream
byte, low byte of `CRC(key0_0, 0)`, high byte of the multiplied key1 state,
bits 2..15 of `CRC(key2_0, 0)`, and the two carry bits, it predicts the XOR of
the two second-byte stream outputs. A 10,000-state seeded test compares this
partial-state calculation against the independent full-state forward
recurrence. This checks the filter equation for planted guesses, but does not
search those guesses or enumerate the 40-bit stage. The targeted suite now has
eight passing tests, with Ruff and mypy clean.

`_stay_first_stage_carry_masks` applies the first file's fixed carry pair and
branches over the four possible carry pairs for every additional file. A
100-state seven-member synthetic test confirms that the direct
double-encryption observation retains the true carry pair in every member
mask. It then intersects all 14 first-byte key1 carry constraints and verifies
that interval lifting retains the planted initial key1. It still does not
enumerate Stay's 40-bit partial-state tuples or execute the first-stage search.

`_stay_first_stage_candidate` now defines the packed 40-bit guess layout:
first stream byte, low `CRC(key0_0, 0)` byte, high byte of `key1_0 * MULT`,
first carry, `CRC(key2_0, 0)` bits 10..15 and 2..9, and the second carry. A
100-state encode/filter regression confirms the planted full-state fields
survive the decoded guess. This prepares the search domain; it does not iterate
the domain. The focused suite now has nine passing tests.

`_stay_first_stage_scan_chunk` adds a half-open range, candidate-count cap,
wall-time check, hit-count cap, and `next_index` cursor for resumable bounded
scans. A split-range regression confirms the next chunk finds a planted
candidate at the boundary. This is a Python reference scanner for correctness
and small chunks; no throughput benchmark was run, and it is not yet suitable
for scanning the complete 2^40 space or exposed as a METIS artifact tool. The
focused suite now has ten passing tests.
