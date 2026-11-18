---
name: ctf-crypto-solve
description: Analyze supplied cryptographic artifacts, encodings and protocol records for defensive evidence and configuration review.
---

# Cryptographic artifact analysis

Work offline on supplied artifacts and authorized keys. Identify the encoding, container,
scheme, key-derivation parameters, nonce/IV, authentication tag and protocol version before
interpreting bytes. Preserve the exact input, byte order, lengths and derivation steps.

Separate source code that describes generation from a transcript containing the observed
ciphertext. If a required key or runtime-generated value is absent, record the missing input;
do not call a live service to turn it into an attack oracle. A packet capture can contain the
transcript even when there is no separate output file. Reassemble complete streams before
parsing; message fragments and terminal echo are not independent cryptographic observations.

Assess nonce reuse, unauthenticated encryption, obsolete algorithms, weak randomness,
key exposure and inconsistent certificate validation at the design/evidence level. Check
standards and library versions before interpreting recovery-phrase or key-derivation formats.
Do not recover another party's credentials, brute-force services or implement a bypass.

If authorized decryption is possible, verify integrity/authentication and retain a reproducible
transformation log. Distinguish authenticated plaintext from a plausible decoding. Use known
benign vectors and negative cases to validate the parser. Pin dependency versions when the
format depends on them; test truncated, reordered and fragmented inputs without live targets.
Report evidence, uncertainty, remediation and a detection or key-management lesson.

Read [the concrete evidence reference](references/encrypted-evidence.md) for ciphertext framing, cryptographic parameters, library defaults and authentication status.
It adds observation coordinates and validation criteria; no exploit, live oracle or sample execution is provided.
