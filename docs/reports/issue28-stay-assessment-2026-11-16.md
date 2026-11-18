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
candidate at the boundary. The bounded chunk was vectorized with NumPy and
cross-checked against the scalar filter on a planted 256-candidate range. A
synthetic local benchmark scanned 16 million candidates in 0.226 seconds on
macOS 27.2.1 arm64, using one process and reporting no hits (about 74.1 million
candidates/second). The measurement harness did not include the current full
multi-member carry-filter path, so it cannot support a 2^40 runtime estimate.
Neither in-sandbox nor target throughput has been measured. The scan is still
not exposed as a METIS artifact tool, and no complete 2^40 range has been
scanned. The focused suite now has ten passing tests.

Review of resumability confirmed that stopping at the hit cap must return the
position immediately after the last emitted hit. Advancing to the end of the
filtered batch would discard later hits from that batch; returning the hit
cursor allows the next chunk to enumerate them. A regression compares capped
and resumed results with the complete scalar survivor list. The focused suite
passed (10 tests).

## Isolated Stage 1 scan (2026-11-18)

Added the `zipcrypto_stay_scan` artifact tool. It recovers the per-member
random headers inside Python, verifies each first byte against the archive,
then compiles and runs a fixed C filter only inside the networkless
`zipcrypto` sandbox profile (2 GiB memory/swap ceiling, four-CPU ceiling,
read-only root, no host mounts). Each request is bounded to 10–300 seconds and
a half-open 40-bit range. Candidate IDs and carry masks are written to 0600
files below `.metis-state/private-stay/`; run events retain only counts,
cursor, timing, and result status.

The native filter passed a real sandbox integration test against the seeded
seven-member synthetic Info-ZIP vector. The planted candidate and all carry
masks matched the independent Python reference; the shard permission check
confirmed mode 0600. Ruff, mypy, and the focused ZipCrypto, session-evidence,
and Stay differential tests passed.

On the official ksnctf #39 archive, the complete 2^40 index domain was scanned
in bounded sandbox chunks. The scan retained 360 first-stage candidates in
private shards. Rechecking their per-member carry masks against the shared
key1 product interval left 88 interval records, whose widths sum to 98,222,960
values before deduplication across carry choices. These intervals are a
substantial reduction, but still require later-stage filtering and key
recovery. No plaintext was
decrypted, no CRC was checked with recovered keys, and no official candidate
was submitted. Do not interpret the completed Stage 1 scan or its private
shards as a recovered ZipCrypto key or a solve. The key-recovery stage remains
unimplemented.

## Stage 2 review decision (2026-11-18)

An independent derivation mapped the paper's proposed 28-bit Stage 2 guess to
8 bits of `crc32(key0_0, 0)` at bits 8–15, 8 bits from the high byte of
`key1_0 * MULT^2`, 10 bits of `crc32(key2_0, 0)` at bits 16–23 and 0–1, plus
two pass-specific carries. `_stay_predict_third_byte_difference` now implements
the partial-state byte-three predictor. An independent bitwise CRC/cipher
oracle test compares its output to 10,000 planted full states and checks that
changing `q8` or a carry can change the prediction. A separate independent
review found no mismatch in byte indexing, CRC low-state derivation, update
carries, or second-stream parity. Exact-head CI at `7921f7f` passed both the
checks and METIS validation workflows.

This validates the predictor only. The caller still must enforce consistency
between `q8` and each Stage 1 interval using
`q8 = ((P * MULT) mod 2^32) >> 24`; the helper does not enumerate Stage 2
guesses, run the candidate search, reconstruct full keys, check all archive
member CRCs, or produce an official verdict. The 360 Stage 1 candidates and
88 carry-interval records remain unrecovered candidates, not a solve. Issue
#28 and ksnctf #39 remain open.
The primary reference is [Stay, “ZIP Attacks with Reduced Known Plaintext,”
§§3–4.1](https://math.ucr.edu/~mike/zipattacks.pdf). The #39 key recovery and
Issue #28 remain open.

## Stage 2 feasibility boundary (2026-11-18)

An independent follow-up inspected only the Stage 1 shard schema and the
bounded CLI boundary. Private shards contain candidate IDs and carry masks;
they do not store the 88 interval records or a `q8` projection. At that point,
the tool exposed Stage 1 scanning only and no Stage 2 computation had been run.

Projecting `q8 = MSB(P * MULT mod 2^32)` over the recorded interval widths would
require about 98,222,960 simple value checks before deduplication (about
`2^26.55` projections). This count is an operation estimate, not measured
runtime. Enumerating the full 28-bit Stage 2 tuple for each of the 360 first
stage hits would be about 96.6 billion base tuples before per-file carry
filtering. That is outside a bounded same-window completion path without a
different algorithm and a resumable, resource-accounted interface. No saved
challenge shard contents were inspected to produce this estimate. Later work
added interval projections and a one-candidate predicate, recorded below, but
has not enumerated the Stage 2 space. Issue #28 and ksnctf #39 remain open.

## Exact Stage 1 interval to q8 projection (2026-11-18)

Added `_stay_q8_carry_masks`, which computes exactly which Stage 2 `q8` values
and second-update carry bits are consistent with a Stage 1 `key1 * MULT` product
interval. It counts modular residues per high-byte and carry-threshold bucket
with Euclidean floor sums, so the 24-bit interval is not enumerated. An
exhaustive small-word oracle compares 500 deterministic intervals against
direct multiplication, and the planted full-state carry-interval test verifies
that the correct q8 and all per-header second-update carries are retained.

The single-candidate Stage 2 predicate checks the multi-member third-byte
differential, intersects all selected second-update carry thresholds into one
shared low-residue interval, then uses a fixed-q8 floor-sum query to verify that
one Stage 1 product value satisfies the joint constraints. It no longer scans
all 256 q8 buckets inside candidate evaluation. Ten deterministic planted
seven-file states passed; modified third-byte differentials were rejected, and
a distinct-pass-carry fixture matched both offsets to the full recurrence.
This tests one 28-bit Stage 2 guess; it does not enumerate the keyspace,
reconstruct full keys, check all member CRCs, or submit a candidate. No official
archive candidate was tested by this predicate. Issue #28 remains open.

## Projection check on saved Stage 1 intervals (2026-11-18)

The interval-to-q8 helper was applied locally to the private Stage 1 shards for
run `0045b063168045c289eaef276dab21c2`. The analysis printed aggregate counts
only: 360 first-stage candidates, 88 interval records, and 98,222,960 summed
interval values. Each of the 88 intervals admits all 256 q8 values, so q8
consistency is a required correctness check but does not reduce the present
Stage 2 search space. Candidate IDs and values were not printed or added to
tracked files. This aggregate analysis is not a Stage 2 search or solve.

## Stage 2 review corrections and bounds (2026-11-18)

An independent follow-up review identified that candidate evaluation must not
scan all 256 q8 buckets and that carry branches need a firm visit bound. The
candidate predicate now tests only its fixed q8 and uses the joint low-residue
query. Stage 1 carry interval construction intersects constraints as each member
is visited and fails closed after 32,768 branch visits. A regression forces the
limit to one visit and confirms the stable bound error. A separate planted
fixture has different first-update carries in the two passes and compares both
second-update offsets to the full cipher recurrence.

The predicate still checks only the supplied low 24 bits of `crc32(key2, 0)`;
it does not establish that a compatible missing high byte of the full key2
state exists, reconstruct full keys, or validate all archive CRCs. Any later
recovery stage must test the missing state bits and all member CRCs before
reporting a candidate.

An independent recovery review refined the raw Stage 2 domain estimate: after
materializing the 88 interval records and treating the two pass-specific carry
choices as internal branches, the partial-state domain is at most
`88 * 2^26 = 5,905,580,032` interval/guess pairs before byte-three filtering.
This corrects the earlier coarse `360 * 2^28` base-tuple estimate for the
current interval representation. It is an operation count, not a measured
runtime or survivor count. Stage 2 currently returns only a Boolean and drops
the product/carry witness needed by later full-state reconstruction. No target
Stage 2 enumeration or key recovery has occurred.

## Full-member forward validation (2026-11-18)

`decrypt_member` now optionally accepts the ten expected Info-ZIP PRNG header
bytes. In that mode it checks both plaintext header check bytes, decrypts the
first ten intermediate header bytes with the reset cipher state and compares
them to the expected PRNG bytes, then validates the complete member body CRC.
A deterministic seven-member Info-ZIP fixture passes this check and agrees
with CPython's independent `zipfile` plaintext oracle. Flipping stored header
bytes 2, 10, or 11 for each member is rejected (21 negative cases).

This validates a supplied complete key state and known PRNG headers; it does
not recover a key, run the Stage 2 search, or solve official #39. The fixture
test is recorded in `tests/test_ctf_zipcrypto.py`.

## Stage 2 product witness (2026-11-18)

The exact q8/residue interval check can now return the first compatible
`key1 * MULT` product. It uses modular floor-sum counts and binary search over
the product interval, with no interval materialization. The Stage 2 predicate
accepts an optional private output list and appends one product only after all
third-byte and shared-carry constraints pass. Calls that only need a Boolean
retain the constant-number-of-floor-sums path.

The reduced-width test compares the witness to the first direct-enumeration
match over 500 seeded intervals. A 24-bit planted singleton check and ten
seven-member planted Stage 2 cases also passed. The focused Stay suite passed
(`17 passed`); Ruff, mypy, and `git diff --check` passed. This provides a
product witness for later recovery; it does not establish that missing key0/key2
bits are consistent, recover a full key, enumerate Stage 2, decrypt #39, or
obtain an official verdict.

## Bounded synthetic Stage 2 sandbox probe (2026-11-18)

The opt-in seven-member synthetic test used the fixed networkless ZipCrypto
container profile (2 GiB, four CPUs). It first checked one planted Stage 1 hit
and one planted Stage 2 guess. Additional Stage 2 chunks scanned `[0, 1000)`
and `[0, 10000)` for that vector. Both completed with zero hits and cursors
1000 and 10000; worker-reported scan times were 0.022 and 0.203 seconds.
These are short zero-hit synthetic measurements, not target throughput.

The estimated 5,905,580,032 interval/guess pairs require at least 5,632
actions at the Stage 2 tool's 1,048,576-candidate action cap, even if each
action finishes instantly. This exceeds the controller's 1,000-action ceiling
and ordinary 40-action run budget. Division by the observed 10,000-guess rate
gives roughly 33 hours as a scale check only; target branching and hit density
are unmeasured. The current worker scans one Stage 1 hit per call and recomputes
its interval branches, so this estimate is optimistic for that interface. A
stronger reduction or batching strategy is needed before a complete Stage 2
attempt. No official archive Stage 2 scan or submission occurred.

## First-member Stage 2 preimage lifting (2026-11-18)

Rechecking [Stay's section 4.1](https://math.ucr.edu/~mike/zipattacks.pdf)
suggested generating the Stage 2 key2/carry guesses that match the first
member's third-byte differential before invoking the shared product-interval
predicate. `_stay_stage2_first_member_preimages` now enumerates the bounded
1,024 key2 partial guesses and four second-update carry pairs for fixed
key0-high and q8 guesses, returning only exact local matches. A separately
generated full-state seven-member vector retained its planted key2/carry tuple;
altering the observed third-byte differential excluded that tuple. This is
local candidate lifting, not a complete reduction of the 5.9-billion-pair
domain: creating every preimage list would still visit the same raw guesses,
and the current Stage 2 worker does not use this primitive. A native batched
generator plus measured sandbox throughput and shared-interval filtering
would be needed to establish a route within the existing action budget.

## Review follow-up: shard contract and cgroup check

Stage 1 returns `candidate_shard` as `private-stay/<run-id>/<uuid>.json`.
Stage 2 now accepts that exact reference as `stage1_shard`, checks the run ID
against the active run, and rejects path traversal and another run's shard.
Stage 2 writes `private-stay/<run-id>/s2-<uuid>.json`, which cannot be passed
back as a Stage 1 shard. The three isolated workers use one injected cgroup
limit check, so their memory, swap, CPU and PID policy stays identical.
The planted seven-member Stage 1 → Stage 2 sandbox test passed with this
contract. These interface changes do not make the full attack feasible.

## Stage 2 interval reuse probe (2026-11-18)

Review follow-up: interval preparation now shares the chunk deadline. An
expired deadline stops preparation before any Stage 2 guess, and an empty
chunk returns without preparing intervals. Differential tests also cover
multiple compatible first-member carry options in a prepared interval set.

The bounded Stage 2 chunk now materializes its Stage 1 carry intervals once
per chunk and reuses them across guesses. The predicate also checks the first
member's exact third-byte condition once per distinct Stage 1 carry pair,
before traversing intervals; it keeps every compatible carry branch. A
regression compares chunk hits against the scalar predicate and confirms one
interval construction. The planted seven-member sandbox test passed. In the
same fixed networkless container, the synthetic zero-hit `[0, 10000)` probe
reported 0.089 seconds, versus 0.203 seconds before these changes. These short,
separate runs are not a target throughput estimate. The current
1,048,576-guess action cap still
requires at least 5,632 actions for the 5,905,580,032 upper-domain pairs,
above both ordinary and hard run caps. Run
`0045b063168045c289eaef276dab21c2` has no wall time left. No official
Stage 2 scan, key recovery, or submission occurred. Further work needs a
native multi-member sieve and full-state reconstruction validated on synthetic
vectors; the first compatible product witness alone may not be the true key.

## Multi-member prediction reuse follow-up (2026-11-18)

The Python Stage 2 predicate now computes each member/carry-pair third-byte
option once per partial guess and rejects incompatible interval branches
before calculating their second-update addends. A 100-interval regression
counts 20 predictor calls for five members with one carry pair each, rather
than repeating predictions for each interval. Deadline checks cover sieve,
interval, and residue work without advancing the resumable cursor for an
interrupted guess. Existing planted-state, differential, and sandbox tests
retain the known witness.

A separate synthetic zero-hit 10,000-guess local probe took 0.093 seconds,
versus 0.092 seconds on the preceding implementation. This does not improve
the raw 5.9-billion-pair bound or establish target throughput. The first-member
preimage research helper is still not used by the production worker. Full key
reconstruction and official #39 Stage 2 verification remain open.

## Vectorized first-member sieve (2026-11-18)

The Stage 2 worker now evaluates the first member's exact third-byte
condition in bounded 65,536-guess NumPy blocks, then runs the existing shared
interval predicate only on survivors. A fixed-seed comparison checks the
vector mask against scalar predictions for all four Stage 1 carry pairs;
the planted Stage 2 guess survives a 513-guess block in both direct and real
networkless sandbox tests. The scalar predicate still decides every hit.

On one planted synthetic seven-member state, a local zero-hit 100,000-guess
probe completed in 0.040 seconds versus 1.040 seconds on the previous head.
The fixed 2 GiB/four-CPU sandbox completed a separate zero-hit 8,388,608-guess
chunk in 2.645 worker seconds, with no hit. These rates do not estimate target
branching or survivor density. The controller now permits at most 2^23 raw
guesses per Stage 2 action, while preserving the 300-second worker timeout,
65,536-guess vector blocks, and private hit shard. The 88 interval records
reported for #39 imply at most 704 such full-range chunks if each record
belongs to a distinct Stage 1 hit; actual hit grouping and overhead remain
unverified. The old run is expired, and no official Stage 2 scan was started.
The tool still lacks full-key reconstruction, so #28 remains open.

## Supplied-product key reconstruction primitive (2026-11-18)

A bounded helper now inverts a *supplied* Stage 1 product to key1, vectorizes
the remaining 16-bit key0 CRC and 8-bit key2 CRC search, filters by the first
member's fourth double-encrypted byte, and checks all seven known ten-byte
headers on scalar survivors. A planted full state was recovered from the
complete 2^24 extra-bit range in 1.199 seconds on a local synthetic vector;
changing the fourth stored byte rejects the planted candidate. The helper
is not exposed as a METIS intent and has not been run against #39. A Stage 2
hit can admit many product values, while the current hit shard stores only
the first compatible witness. Enumerating every compatible product and then
checking all member CRCs is still required before any key recovery claim.

The predicate can now enumerate up to 4,096 distinct compatible products for
a single Stage 2 guess using repeated exact q8/residue witness searches. One
planted seven-member guess yielded 668 products; the true product was among
them. This is a synthetic workload observation, not a target survivor count.
The production Stage 2 shard still records only the first witness, but the
new `zipcrypto_stay_recover` route re-enumerates compatible products from a
private Stage 2 hit. It resumes over product and extra-bit cursors, runs in
the fixed networkless sandbox, checks all encrypted members' CRCs, and writes
verified key states to a mode-0600 run-private shard. The public response
contains counts and cursors, not key material. A planted seven-member state
was recovered through this route and its private shard in a real sandbox.
The test starts at the known true product index; exhaustive traversal of all
668 products and target #39 recovery were not run. The route caps each action
at 300 seconds, 4,096 products, and 2^28 extra-bit candidates. Target
feasibility and official verification remain open, so #28 remains open.

## Review follow-up: bounded continuation and dense-hit probe (2026-11-19)

The planted seven-member integration test now makes successive sandbox calls:
the first stops after 1,024 extra-bit candidates, and the second resumes from
the returned extra cursor and recovers the same state. A separate direct
helper test processes the preceding compatible product under a one-product
cap, then resumes from its returned product cursor and recovers the planted
state. Both paths assert the cursor values. This checks continuation on the
synthetic vector, not exhaustive traversal of every compatible product.

For a deliberately dense synthetic interval, the first encrypted member's
observations were repeated seven times over a 65,536-guess window containing
the planted guess. The exact Stage 2 scan returned 692 hits and completed in
0.136 seconds locally; the hit count is retained as a regression assertion.
Repeated observations reduce independent filtering and stress the survivor
path, but do not model the target's distinct member headers or predict #39
runtime. This Draft PR is scoped to bounded algorithm and controller changes.
An independent end-to-end #39 verdict remains outside its acceptance evidence.

## Independent full-product inverse vector (2026-11-19)

An opt-in slow regression now creates 16 random ten-byte headers and their
two-pass ciphertext with a separate bitwise CRC/encryptor. The planted state
was chosen without using the METIS inverse routines. For its true Stage 1
index and Stage 2 guess, the inverse search enumerated 33 compatible product
values. Nine successive bounded calls traversed all 33 products, recovering
exactly the planted full key state; the final call returned `complete`.
`METIS_TEST_SLOW=1` ran the test successfully locally. This exercises complete
product traversal on an independently generated inverse vector. It does not
scan the full Stage 1 or Stage 2 search spaces, construct a ZIP payload, or
provide an official #39 verdict. Issue #28 remains open.
