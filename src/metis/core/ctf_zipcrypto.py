"""Traditional PKWARE encryption (ZipCrypto) analysis for CTF archives (Issue #28).

* ``Keys`` and the cipher primitives (APPNOTE 6.1).
* Known-plaintext attack of Biham and Kocher (FSE 1994), ported from bkcrack by Joachim
  Hotonnier (zlib licence, https://github.com/kimci86/bkcrack): Z-reduction over the 2^22
  candidates of key2[10,32) (vectorised with numpy) followed by the key2 -> key1 -> key0 search.
  Needs at least 12 known plaintext bytes, 8 of them contiguous, of the *encrypted* stream (the
  12-byte encryption header counts, at offsets -12..-1).
* Info-ZIP header analysis after Stay, "ZIP Attacks with Reduced Known Plaintext" (FSE 2001,
  section 4): Info-ZIP seeds rand() once per run, takes ten bytes per member and encrypts them
  twice under the same initial key state, so the first header byte of every member *is* a
  rand() byte. ``infozip_seed`` recovers the seed (glibc TYPE_3 or MSVC LCG) by a bounded search
  and predicts all ten header bytes of every member.

Not implemented: Stay's key recovery from the double-encrypted header (about 2^39 cipher steps
in the paper, hours of native code) - the tools report it as ``work_exceeds_budget``.
The first-stage 2^40 partial-state scan is available only through the bounded isolated
``zipcrypto_stay_scan`` worker; it does not recover keys. All challenge inputs are handled
inside Python, and the generated scan kernel runs only inside the isolated container.
"""
from __future__ import annotations

import multiprocessing
import os
import struct
import time
import zlib
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import numpy as np

M32 = 0xFFFFFFFF
MULT = 0x08088405
MULTINV = 0xD94FA8CD
MAXDIFF24 = 0x00FFFFFF + 0xFF
MAXDIFF26 = 0x03FFFFFF + 0xFF
CONTIGUOUS = 8
ATTACK_SIZE = 12


def _stay_carry_interval(low_addends: tuple[int, ...], carries: tuple[int, ...],
                         *, bits: int = 24) -> tuple[int, int] | None:
    """Intersect exact low-word ranges implied by Stay's guessed carry bits.

    For each update, ``carry`` is the high-word carry of ``P_low + addend``.
    A zero carry gives an inclusive upper bound; a one carry gives an inclusive
    lower bound. ``None`` means the guesses are mutually inconsistent.
    """
    if (len(low_addends) != len(carries) or type(bits) is not int
            or not 1 <= bits <= 24):
        raise ValueError("carry constraints or word width are invalid")
    modulus = 1 << bits
    if any(type(value) is not int or not 0 <= value < modulus for value in low_addends):
        raise ValueError("carry addends must fit the low word")
    if any(type(carry) is not int or carry not in (0, 1) for carry in carries):
        raise ValueError("carry guesses must be zero or one")

    lower, upper = 0, modulus - 1
    for addend, carry in zip(low_addends, carries, strict=True):
        threshold = modulus - addend
        if carry:
            lower = max(lower, threshold)
        else:
            upper = min(upper, threshold - 1)
        if lower > upper:
            return None
    return lower, upper


def _stay_key1_product_interval(addends: tuple[int, ...], top_bytes: tuple[int, ...],
                                carries: tuple[int, ...], *, bits: int = 24
                                ) -> tuple[int, int, int] | None:
    """Recover the shared high byte and low-word interval of ``key1 * MULT``.

    Each observation is the high byte of ``(key1 + addend) * MULT + 1``.
    A guessed carry from adding the known ``addend * MULT + 1`` to the
    multiplied key fixes the product high byte and contributes one exact
    interval constraint on its low ``bits``. This is the candidate-lifting
    primitive described in Stay's divide-and-conquer stages.
    """
    if (len(addends) != len(top_bytes) or len(addends) != len(carries)
            or not addends or type(bits) is not int or not 1 <= bits <= 24):
        raise ValueError("Stay product observations or word width are invalid")
    limit = 1 << bits
    if any(type(value) is not int or not 0 <= value < limit for value in addends):
        raise ValueError("Stay addends must fit the low word")
    if any(type(value) is not int or not 0 <= value <= 0xFF for value in top_bytes):
        raise ValueError("Stay top bytes must be bytes")
    if any(type(carry) is not int or carry not in (0, 1) for carry in carries):
        raise ValueError("carry guesses must be zero or one")

    low_mask = limit - 1
    product_high: int | None = None
    low_addends: list[int] = []
    for addend, top_byte, carry in zip(addends, top_bytes, carries, strict=True):
        offset = addend * MULT + 1
        inferred_high = (top_byte - (offset >> bits) - carry) & 0xFF
        if product_high is None:
            product_high = inferred_high
        elif product_high != inferred_high:
            return None
        low_addends.append(offset & low_mask)

    interval = _stay_carry_interval(tuple(low_addends), carries, bits=bits)
    if interval is None or product_high is None:
        return None
    return product_high, interval[0], interval[1]


def _stay_lift_key1_candidates(product_interval: tuple[int, int, int], *, bits: int = 24
                               ) -> Iterator[int]:
    """Lift a product interval to key1 values using the odd ZipCrypto multiplier."""
    if type(bits) is not int or not 1 <= bits <= 24:
        raise ValueError("Stay product word width is invalid")
    if (len(product_interval) != 3
            or any(type(value) is not int for value in product_interval)):
        raise ValueError("Stay product interval must contain three integers")
    product_high, lower, upper = product_interval
    limit = 1 << bits
    if not 0 <= product_high <= 0xFF or not 0 <= lower <= upper < limit:
        raise ValueError("Stay product interval is out of range")
    word_mask = (1 << (bits + 8)) - 1
    multiplier_inverse = pow(MULT, -1, word_mask + 1)
    product_base = product_high << bits
    for low in range(lower, upper + 1):
        yield ((product_base | low) * multiplier_inverse) & word_mask


def _stay_predict_second_byte_difference(random_first: int, first_stream: int,
                                         key0_crc_low: int, key1_product_high: int,
                                         key2_crc_bits_2_15: int, first_carry: int,
                                         second_carry: int) -> int:
    """Predict the two-pass second-byte stream XOR from Stay's partial guesses."""
    byte_values = (random_first, first_stream, key0_crc_low, key1_product_high)
    if any(type(value) is not int or not 0 <= value <= 0xFF for value in byte_values):
        raise ValueError("Stay byte guesses must be bytes")
    if (type(key2_crc_bits_2_15) is not int or not 0 <= key2_crc_bits_2_15 <= 0xFFFC
            or key2_crc_bits_2_15 & 0x3):
        raise ValueError("Stay key2 CRC guess must contain bits 2 through 15")
    if any(type(carry) is not int or carry not in (0, 1) for carry in (first_carry, second_carry)):
        raise ValueError("carry guesses must be zero or one")

    first_low = key0_crc_low ^ (CRCTAB[random_first] & 0xFF)
    second_first_plaintext = random_first ^ first_stream
    second_low = key0_crc_low ^ (CRCTAB[second_first_plaintext] & 0xFF)
    first_offset = first_low * MULT + 1
    second_offset = second_low * MULT + 1
    first_key1_high = (key1_product_high + (first_offset >> 24) + first_carry) & 0xFF
    second_key1_high = (key1_product_high + (second_offset >> 24) + second_carry) & 0xFF

    first_key2_low = (key2_crc_bits_2_15 ^ CRCTAB[first_key1_high]) & 0xFFFC
    second_key2_low = (key2_crc_bits_2_15 ^ CRCTAB[second_key1_high]) & 0xFFFC

    def stream(key2_low: int) -> int:
        value = (key2_low & 0xFFFF) | 2
        return (value * (value ^ 1) >> 8) & 0xFF

    return stream(first_key2_low) ^ stream(second_key2_low)


def _stay_first_stage_carry_masks(random_firsts: tuple[int, ...],
                                  observed_differences: tuple[int, ...],
                                  first_stream: int, key0_crc_low: int,
                                  key1_product_high: int, key2_crc_bits_2_15: int,
                                  first_carry: int, second_carry: int
                                  ) -> tuple[int, ...] | None:
    """Filter a first-stage partial-state guess across five shared-key files.

    The first file's carry pair is part of the 40-bit guess. For each later
    file, return a four-bit mask of carry pairs that satisfy its observed
    second-byte differential. An empty mask rejects the candidate.
    """
    if (len(random_firsts) != len(observed_differences) or len(random_firsts) < 5
            or any(type(value) is not int or not 0 <= value <= 0xFF
                   for value in (*random_firsts, *observed_differences))):
        raise ValueError("Stay first-stage observations require five or more byte pairs")
    if any(type(carry) is not int or carry not in (0, 1)
           for carry in (first_carry, second_carry)):
        raise ValueError("carry guesses must be zero or one")

    first = _stay_predict_second_byte_difference(
        random_firsts[0], first_stream, key0_crc_low, key1_product_high,
        key2_crc_bits_2_15, first_carry, second_carry)
    if first != observed_differences[0]:
        return None
    masks = [1 << (first_carry * 2 + second_carry)]
    for random_first, observed in zip(random_firsts[1:], observed_differences[1:], strict=True):
        mask = 0
        for carry1 in (0, 1):
            for carry2 in (0, 1):
                predicted = _stay_predict_second_byte_difference(
                    random_first, first_stream, key0_crc_low, key1_product_high,
                    key2_crc_bits_2_15, carry1, carry2)
                if predicted == observed:
                    mask |= 1 << (carry1 * 2 + carry2)
        if not mask:
            return None
        masks.append(mask)
    return tuple(masks)


def _stay_first_stage_candidate(index: int, random_firsts: tuple[int, ...],
                                observed_differences: tuple[int, ...]
                                ) -> tuple[int, ...] | None:
    """Decode one packed 40-bit Stay guess and apply its multi-file filter."""
    if type(index) is not int or not 0 <= index < 1 << 40:
        raise ValueError("Stay first-stage candidate index must be a 40-bit integer")
    first_stream = index & 0xFF
    key0_crc_low = index >> 8 & 0xFF
    key1_product_high = index >> 16 & 0xFF
    first_carry = index >> 24 & 1
    key2_crc_bits_2_15 = ((index >> 25 & 0x3F) << 10) | ((index >> 31 & 0xFF) << 2)
    second_carry = index >> 39 & 1
    return _stay_first_stage_carry_masks(
        random_firsts, observed_differences, first_stream, key0_crc_low,
        key1_product_high, key2_crc_bits_2_15, first_carry, second_carry)


def _stay_first_stage_key1_intervals(index: int, carry_masks: tuple[int, ...],
                                     random_firsts: tuple[int, ...]
                                     ) -> Iterator[tuple[tuple[int, int, int], tuple[int, ...]]]:
    """Lift a filtered 40-bit guess through shared key1 carry intervals.

    Each yielded pair contains a product interval and the carry-pair index
    selected for each member. Callers can enumerate actual key1 values from the
    interval only when a later stage needs them. This is a Stage 1 consistency
    filter, not the later key-recovery stage.
    """
    if type(index) is not int or not 0 <= index < 1 << 40:
        raise ValueError("Stay first-stage candidate index must be a 40-bit integer")
    if (len(carry_masks) != len(random_firsts) or len(random_firsts) < 5
            or any(type(mask) is not int or not 1 <= mask <= 0xF for mask in carry_masks)
            or any(type(value) is not int or not 0 <= value <= 0xFF for value in random_firsts)):
        raise ValueError("Stay carry masks and random header bytes are invalid")
    first_stream = index & 0xFF
    key0_crc_low = index >> 8 & 0xFF
    product_high = index >> 16 & 0xFF
    carry_options = [tuple(pair for pair in range(4) if mask & (1 << pair))
                     for mask in carry_masks]
    first_carry_pair = index >> 24 & 1, index >> 39 & 1
    if (first_carry_pair[0] * 2 + first_carry_pair[1]) not in carry_options[0]:
        return
    carry_options[0] = (first_carry_pair[0] * 2 + first_carry_pair[1],)

    choices = [0] * len(random_firsts)

    def visit(member: int) -> Iterator[tuple[tuple[int, int, int], tuple[int, ...]]]:
        if member < len(random_firsts):
            for pair in carry_options[member]:
                choices[member] = pair
                yield from visit(member + 1)
            return
        addends: list[int] = []
        top_bytes: list[int] = []
        carries: list[int] = []
        for random_first, pair in zip(random_firsts, choices, strict=True):
            first_low = key0_crc_low ^ (CRCTAB[random_first] & 0xFF)
            second_low = key0_crc_low ^ (CRCTAB[random_first ^ first_stream] & 0xFF)
            first_carry, second_carry = pair >> 1, pair & 1
            for low, carry in ((first_low, first_carry), (second_low, second_carry)):
                offset = low * MULT + 1
                addends.append(low)
                carries.append(carry)
                top_bytes.append((product_high + (offset >> 24) + carry) & 0xFF)
        interval = _stay_key1_product_interval(tuple(addends), tuple(top_bytes), tuple(carries))
        if interval is not None:
            yield interval, tuple(choices)

    yield from visit(0)


def _stay_predict_second_byte_difference_np(indices: np.ndarray, random_first: int,
                                             first_stream: np.ndarray, key0_crc_low: np.ndarray,
                                             key1_product_high: np.ndarray,
                                             key2_crc_bits_2_15: np.ndarray,
                                             first_carry: int | np.ndarray,
                                             second_carry: int | np.ndarray) -> np.ndarray:
    """Vectorized partial-state predictor for one header observation."""
    first_low = key0_crc_low ^ (CRCTAB_NP[random_first] & np.uint32(0xFF))
    second_first_plaintext = random_first ^ first_stream
    second_low = key0_crc_low ^ (CRCTAB_NP[second_first_plaintext] & np.uint32(0xFF))
    first_offset = first_low.astype(np.uint64) * np.uint64(MULT) + np.uint64(1)
    second_offset = second_low.astype(np.uint64) * np.uint64(MULT) + np.uint64(1)
    first_high = (key1_product_high + (first_offset >> np.uint64(24)) + first_carry) & 0xFF
    second_high = (key1_product_high + (second_offset >> np.uint64(24)) + second_carry) & 0xFF
    first_key2 = (key2_crc_bits_2_15 ^ CRCTAB_NP[first_high.astype(np.intp)]) & 0xFFFC
    second_key2 = (key2_crc_bits_2_15 ^ CRCTAB_NP[second_high.astype(np.intp)]) & 0xFFFC
    first_value = (first_key2.astype(np.uint64) & 0xFFFF) | np.uint64(2)
    second_value = (second_key2.astype(np.uint64) & 0xFFFF) | np.uint64(2)
    first_stream2 = (first_value * (first_value ^ np.uint64(1)) >> np.uint64(8)) & 0xFF
    second_stream2 = (second_value * (second_value ^ np.uint64(1)) >> np.uint64(8)) & 0xFF
    # Keep the index argument explicit to make accidental array reordering visible
    # at call sites; all outputs have the same candidate axis.
    if len(indices) != len(first_stream2):
        raise ValueError("Stay vector candidate arrays have inconsistent lengths")
    return (first_stream2 ^ second_stream2).astype(np.uint8)


def _stay_first_stage_scan_chunk(random_firsts: tuple[int, ...],
                                 observed_differences: tuple[int, ...], start: int, stop: int,
                                 *, max_candidates: int = 100_000,
                                 seconds: float = 30.0, max_hits: int = 4096
                                 ) -> dict[str, Any]:
    """Vector-scan a bounded 40-bit range and return a resumable cursor."""
    if (type(start) is not int or type(stop) is not int or not 0 <= start <= stop <= 1 << 40):
        raise ValueError("Stay scan range must be within the 40-bit candidate space")
    if type(max_candidates) is not int or not 1 <= max_candidates <= 1 << 40:
        raise ValueError("Stay scan candidate bound must be between 1 and 2^40")
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not 0 < seconds <= 300):
        raise ValueError("Stay scan deadline must be between zero and 300 seconds")
    if type(max_hits) is not int or not 1 <= max_hits <= 4096:
        raise ValueError("Stay scan hit bound must be between 1 and 4096")
    if (len(random_firsts) != len(observed_differences) or len(random_firsts) < 5
            or any(type(value) is not int or not 0 <= value <= 0xFF
                   for value in (*random_firsts, *observed_differences))):
        raise ValueError("Stay scan requires five or more pairs of observation bytes")
    bounded_stop = min(stop, start + max_candidates)
    deadline = time.monotonic() + seconds
    hits: list[tuple[int, tuple[int, ...]]] = []
    cursor = start
    batch_size = 1 << 20
    while cursor < bounded_stop:
        if time.monotonic() >= deadline:
            break
        batch_stop = min(cursor + batch_size, bounded_stop)
        indices = np.arange(cursor, batch_stop, dtype=np.uint64)
        first_stream = (indices & np.uint64(0xFF)).astype(np.uint32)
        key0_crc_low = (indices >> np.uint64(8) & np.uint64(0xFF)).astype(np.uint32)
        key1_product_high = (indices >> np.uint64(16) & np.uint64(0xFF)).astype(np.uint64)
        first_carry = (indices >> np.uint64(24) & np.uint64(1)).astype(np.uint64)
        key2_crc_bits_2_15 = (
            ((indices >> np.uint64(25) & np.uint64(0x3F)) << np.uint64(10))
            | ((indices >> np.uint64(31) & np.uint64(0xFF)) << np.uint64(2))
        ).astype(np.uint32)
        second_carry = (indices >> np.uint64(39) & np.uint64(1)).astype(np.uint64)
        first_prediction = _stay_predict_second_byte_difference_np(
            indices, random_firsts[0], first_stream, key0_crc_low, key1_product_high,
            key2_crc_bits_2_15, first_carry, second_carry)
        keep = first_prediction == observed_differences[0]
        indices = indices[keep]
        first_stream = first_stream[keep]
        key0_crc_low = key0_crc_low[keep]
        key1_product_high = key1_product_high[keep]
        key2_crc_bits_2_15 = key2_crc_bits_2_15[keep]
        carry_masks = np.zeros((len(random_firsts), len(indices)), dtype=np.uint8)
        if len(indices):
            carry_masks[0] = (1 << (first_carry[keep] * 2 + second_carry[keep])).astype(np.uint8)
        for member_index in range(1, len(random_firsts)):
            member_mask = np.zeros(len(indices), dtype=np.uint8)
            for carry1 in (0, 1):
                for carry2 in (0, 1):
                    prediction = _stay_predict_second_byte_difference_np(
                        indices, random_firsts[member_index], first_stream, key0_crc_low,
                        key1_product_high, key2_crc_bits_2_15, carry1, carry2)
                    member_mask |= (prediction == observed_differences[member_index]).astype(np.uint8) << (
                        carry1 * 2 + carry2)
            keep = member_mask != 0
            indices = indices[keep]
            first_stream = first_stream[keep]
            key0_crc_low = key0_crc_low[keep]
            key1_product_high = key1_product_high[keep]
            key2_crc_bits_2_15 = key2_crc_bits_2_15[keep]
            carry_masks = carry_masks[:, keep]
            member_mask = member_mask[keep]
            carry_masks[member_index] = member_mask
            if not len(indices):
                break
        if len(indices):
            room = max_hits - len(hits)
            take = min(room, len(indices))
            hit_indices = indices[:take]
            for position, candidate in enumerate(hit_indices):
                hits.append((int(candidate), tuple(int(value) for value in carry_masks[:, position])))
            if take < len(indices) or len(hits) >= max_hits:
                # Resume just after the last returned hit. The remaining
                # survivors in this filtered batch must be emitted by the next
                # call rather than skipped.
                cursor = int(hit_indices[-1]) + 1
                break
        cursor = batch_stop
    return {"next_index": cursor, "complete": cursor >= stop,
            "scanned": cursor - start, "hits": tuple(hits)}


def _stay_first_stage_scan_parallel(random_firsts: tuple[int, ...],
                                    observed_differences: tuple[int, ...], start: int, stop: int,
                                    *, max_candidates: int = 1 << 40, seconds: float = 300.0,
                                    max_hits: int = 4096, workers: int = 4) -> dict[str, Any]:
    """Scan consecutive 1M ranges in parallel while retaining a gap-free cursor."""
    if (type(start) is not int or type(stop) is not int or not 0 <= start <= stop <= 1 << 40):
        raise ValueError("Stay scan range must be within the 40-bit candidate space")
    if type(max_candidates) is not int or not 1 <= max_candidates <= 1 << 40:
        raise ValueError("Stay scan candidate bound must be between 1 and 2^40")
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not 0 < seconds <= 300):
        raise ValueError("Stay scan deadline must be between zero and 300 seconds")
    if type(max_hits) is not int or not 1 <= max_hits <= 4096:
        raise ValueError("Stay scan hit bound must be between 1 and 4096")
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError("Stay scan workers must be between one and four")
    if (len(random_firsts) != len(observed_differences) or len(random_firsts) < 5
            or any(type(value) is not int or not 0 <= value <= 0xFF
                   for value in (*random_firsts, *observed_differences))):
        raise ValueError("Stay scan requires five or more pairs of observation bytes")

    bounded_stop = min(stop, start + max_candidates)
    deadline = time.monotonic() + seconds
    cursor = start
    hits: list[tuple[int, tuple[int, ...]]] = []
    batch_size = 1 << 20
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while cursor < bounded_stop:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ranges = [(left, min(left + batch_size, bounded_stop))
                      for left in range(cursor, min(cursor + batch_size * workers, bounded_stop), batch_size)]
            futures = [pool.submit(_stay_first_stage_scan_chunk,
                                   random_firsts, observed_differences, left, right,
                                   max_candidates=right - left, seconds=remaining,
                                   max_hits=max_hits)
                       for left, right in ranges]
            results = [future.result() for future in futures]
            wave_cursor = cursor
            for (left, _right), result in zip(ranges, results, strict=True):
                if left != wave_cursor:
                    raise RuntimeError("Stay parallel scan lost a contiguous range")
                for candidate, masks in result["hits"]:
                    hits.append((candidate, masks))
                    if len(hits) >= max_hits:
                        return {"next_index": candidate + 1, "complete": candidate + 1 >= stop,
                                "scanned": candidate + 1 - start, "hits": tuple(hits),
                                "seconds": round(time.monotonic() - (deadline - seconds), 3)}
                wave_cursor = int(result["next_index"])
                if not result["complete"]:
                    cursor = wave_cursor
                    break
            else:
                cursor = wave_cursor
    return {"next_index": cursor, "complete": cursor >= stop,
            "scanned": cursor - start, "hits": tuple(hits),
            "seconds": round(time.monotonic() - (deadline - seconds), 3)}


def _tables() -> tuple[list[int], list[int]]:
    crc, inv = [0] * 256, [0] * 256
    for byte in range(256):
        value = byte
        for _ in range(8):
            value = value >> 1 ^ 0xEDB88320 if value & 1 else value >> 1
        crc[byte] = value
        inv[value >> 24] = (value << 8 ^ byte) & M32
    return crc, inv


CRCTAB, CRCINV = _tables()
CRCTAB_NP = np.array(CRCTAB, dtype=np.uint32)
CRCINV_NP = np.array(CRCINV, dtype=np.uint32)


def crc32(value: int, byte: int) -> int:
    return value >> 8 ^ CRCTAB[(value ^ byte) & 0xFF]


def crc32inv(value: int, byte: int) -> int:
    return (value << 8 & M32) ^ CRCINV[value >> 24] ^ byte


def _keystream_tables() -> tuple[list[int], list[list[list[int]]], np.ndarray, np.ndarray]:
    stream = [0] * (1 << 14)
    lists: list[list[list[int]]] = [[[] for _ in range(64)] for _ in range(256)]
    for z in range(0, 1 << 16, 4):
        k = ((z | 2) * (z | 3) >> 8) & 0xFF
        stream[z >> 2] = k
        lists[k][z >> 10].append(z)
    width = max(len(bucket) for row in lists for bucket in row)
    padded = np.zeros((256, 64, width), dtype=np.uint32)
    valid = np.zeros((256, 64, width), dtype=bool)
    for k in range(256):
        for bucket in range(64):
            for slot, value in enumerate(lists[k][bucket]):
                padded[k, bucket, slot] = value
                valid[k, bucket, slot] = True
    return stream, lists, padded, valid


KEYSTREAM, ZI_2_16, ZI_PADDED, ZI_VALID = _keystream_tables()
ZI_EXISTS = ZI_VALID.any(axis=2)  # [k, bucket]


def _fibers() -> tuple[list[list[int]], list[list[int]]]:
    two: list[list[int]] = [[] for _ in range(256)]
    three: list[list[int]] = [[] for _ in range(256)]
    product = 0
    for x in range(256):
        high = product >> 24
        two[high].append(x)
        two[(high + 1) % 256].append(x)
        three[(high + 255) % 256].append(x)
        three[high].append(x)
        three[(high + 1) % 256].append(x)
        product = (product + MULTINV) & M32
    return two, three


FIBER2, FIBER3 = _fibers()
FIBER2_WIDTH = max(len(item) for item in FIBER2)
FIBER2_NP = np.zeros((256, FIBER2_WIDTH), dtype=np.uint64)
FIBER2_OK = np.zeros((256, FIBER2_WIDTH), dtype=bool)
for _index, _row in enumerate(FIBER2):
    FIBER2_NP[_index, :len(_row)] = _row
    FIBER2_OK[_index, :len(_row)] = True
CRCTAB_U64 = CRCTAB_NP.astype(np.uint64)
CRCINV_U64 = CRCINV_NP.astype(np.uint64)
FIBER3_WIDTH = max(len(item) for item in FIBER3)
FIBER3_NP = np.zeros((256, FIBER3_WIDTH), dtype=np.uint32)
FIBER3_OK = np.zeros((256, FIBER3_WIDTH), dtype=bool)
for _index, _row in enumerate(FIBER3):
    FIBER3_NP[_index, :len(_row)] = _row
    FIBER3_OK[_index, :len(_row)] = True


@dataclass
class Keys:
    x: int = 0x12345678
    y: int = 0x23456789
    z: int = 0x34567890

    @classmethod
    def from_password(cls, password: bytes) -> Keys:
        keys = cls()
        for byte in password:
            keys.update(byte)
        return keys

    def k(self) -> int:
        temp = (self.z & 0xFFFF) | 2
        return (temp * (temp ^ 1) >> 8) & 0xFF

    def update(self, plain: int) -> None:
        self.x = crc32(self.x, plain)
        self.y = ((self.y + (self.x & 0xFF)) * MULT + 1) & M32
        self.z = crc32(self.z, self.y >> 24)

    def update_backward(self, cipher: int) -> None:
        self.z = crc32inv(self.z, self.y >> 24)
        self.y = ((self.y - 1) * MULTINV - (self.x & 0xFF)) & M32
        self.x = crc32inv(self.x, cipher ^ self.k())

    def copy(self) -> Keys:
        return Keys(self.x, self.y, self.z)

    def decrypt(self, data: bytes) -> bytes:
        keys, out = self.copy(), bytearray()
        for byte in data:
            plain = byte ^ keys.k()
            keys.update(plain)
            out.append(plain)
        return bytes(out)

    def encrypt(self, data: bytes) -> bytes:
        keys, out = self.copy(), bytearray()
        for byte in data:
            out.append(byte ^ keys.k())
            keys.update(byte)
        return bytes(out)

    def hex(self) -> dict[str, str]:
        return {"x": f"{self.x:08x}", "y": f"{self.y:08x}", "z": f"{self.z:08x}"}


class BudgetExceeded(RuntimeError):
    pass


# -- Biham-Kocher known-plaintext attack ---------------------------------------------------------------
def z_reduction(keystream: list[int], deadline: float) -> tuple[np.ndarray, int]:
    """Candidates for key2[2,32) at the returned index (bkcrack Zreduction, vectorised)."""
    index = len(keystream) - 1
    shifted = np.arange(1 << 22, dtype=np.uint32)
    current = (shifted[ZI_EXISTS[keystream[index], shifted & 63]] << 10).astype(np.uint32)
    best, best_index, best_size = current, index, 1 << 16
    tracking = False
    for i in range(index, CONTIGUOUS - 1, -1):
        if time.monotonic() > deadline:
            raise BudgetExceeded("z-reduction")
        buckets = (current & 0xFFFF) >> 10
        rows, ok = ZI_PADDED[keystream[i], buckets], ZI_VALID[keystream[i], buckets]
        full = (current[:, None] | rows)[ok]
        previous = ((full << np.uint32(8)) ^ CRCINV_NP[full >> 24]) & np.uint32(0xFFFFFC00)
        previous = previous[ZI_EXISTS[keystream[i - 1], (previous >> 10) & 63]]
        previous = np.unique(previous)
        count = int(ZI_VALID[keystream[i - 1], (previous & 0xFFFF) >> 10].sum())
        if count <= best_size:
            tracking, best, best_index, best_size = True, previous, i - 1, count
        current = previous
    if not tracking:
        best, best_index = current, CONTIGUOUS - 1
    buckets = (best & 0xFFFF) >> 10
    rows, ok = ZI_PADDED[keystream[best_index], buckets], ZI_VALID[keystream[best_index], buckets]
    return np.unique((best[:, None] | rows)[ok]), best_index


class _Attack:
    def __init__(self, ciphertext: bytes, plaintext: bytes, offset: int, extra: dict[int, int], index: int):
        self.ciphertext, self.plaintext, self.offset, self.extra = ciphertext, plaintext, offset, extra
        self.keystream = [p ^ ciphertext[offset + i] for i, p in enumerate(plaintext)]
        self.index = index + 1 - CONTIGUOUS
        self.zlist, self.ylist, self.xlist = [0] * 8, [0] * 8, [0] * 8
        self.solutions: list[Keys] = []

    def carryout(self, z7: int) -> None:
        self.zlist[7] = z7
        self._z(7)

    def _z(self, i: int) -> None:
        z, y = self.zlist, self.ylist
        if i:
            zim1_10_32 = crc32inv(z[i], 0) & 0xFFFFFC00
            for zim1_2_16 in ZI_2_16[self.keystream[self.index + i - 1]][(zim1_10_32 & 0xFFFF) >> 10]:
                z[i - 1] = zim1_10_32 | zim1_2_16
                z[i] &= 0xFFFFFFFC
                z[i] |= (crc32inv(z[i], 0) ^ z[i - 1]) >> 8
                if i < 7:
                    y[i + 1] = (crc32inv(z[i + 1], 0) ^ z[i]) << 24 & M32
                self._z(i - 1)
                if self.solutions:
                    return
            return
        # Z-list complete: enumerate y7[8,24) and the matching y7[0,8), then walk the Y-list down to
        # y3 and test the X-list for all candidates at once (numpy); survivors get the exact checks.
        high7, high6 = y[7] >> 24, y[6] & 0xFF000000
        steps = np.arange(1 << 16, dtype=np.uint64)
        base = ((MULTINV * high7 << 24) - MULTINV) & M32
        prod = (np.uint64(base) + steps * np.uint64(MULTINV << 8)) & np.uint64(M32)
        rows = (((high6 >> 24) - (prod >> np.uint64(24))) & np.uint64(0xFF)).astype(np.int64)
        low = FIBER3_NP[rows].astype(np.uint64)
        ok = FIBER3_OK[rows] & (((prod[:, None] + np.uint64(MULTINV) * low - np.uint64(high6)) & np.uint64(M32))
                                 <= MAXDIFF24)
        step, column = np.nonzero(ok)
        ycols = {7: (low[step, column] | (step.astype(np.uint64) << np.uint64(8))
                     | np.uint64(y[7] & 0xFF000000))}
        xcols: dict[int, np.ndarray] = {}
        mask = np.uint64(M32)
        for level in range(7, 3, -1):
            current = ycols[level]
            fy = ((current - np.uint64(1)) * np.uint64(MULTINV)) & mask
            ffy = ((fy - np.uint64(1)) * np.uint64(MULTINV)) & mask
            top = np.uint64(y[level - 2] & 0xFF000000)
            rows2 = (((ffy - top) & mask) >> np.uint64(24)).astype(np.int64)
            x0 = FIBER2_NP[rows2]
            yim1 = (fy[:, None] - x0) & mask
            keep = (FIBER2_OK[rows2] & (((ffy[:, None] - np.uint64(MULTINV) * x0 - top) & mask) <= MAXDIFF24)
                    & ((yim1 >> np.uint64(24)) == np.uint64(y[level - 1] >> 24)))
            parent, slot = np.nonzero(keep)
            if not len(parent):
                return
            ycols = {key: value[parent] for key, value in ycols.items()}
            xcols = {key: value[parent] for key, value in xcols.items()}
            ycols[level - 1] = yim1[parent, slot]
            xcols[level] = x0[parent, slot]
        p, start = self.plaintext, self.index
        xs = {4: xcols[4]}
        for level in range(5, 8):
            previous = xs[level - 1]
            crc = (previous >> np.uint64(8)) ^ CRCTAB_U64[((previous ^ np.uint64(p[start + level - 1])) & np.uint64(0xFF))
                                                         .astype(np.int64)]
            xs[level] = (crc & np.uint64(0xFFFFFF00)) | xcols[level]
        value = xs[7]
        for level in range(6, 2, -1):
            value = (((value << np.uint64(8)) & mask) ^ CRCINV_U64[(value >> np.uint64(24)).astype(np.int64)]
                     ^ np.uint64(p[start + level]))
        y1_26_32 = np.uint64((crc32inv(z[1], 0) ^ z[0]) << 24 & 0xFC000000)
        check = ((((ycols[3] - np.uint64(1)) * np.uint64(MULTINV) - (value & np.uint64(0xFF)) - np.uint64(1))
                  * np.uint64(MULTINV) - y1_26_32) & mask) <= MAXDIFF26
        for row in np.nonzero(check)[0].tolist():
            for level in range(3, 8):
                y[level] = int(ycols[level][row])
            for level in range(4, 8):
                self.xlist[level] = int(xcols[level][row])
            self._test()
            if self.solutions:
                return

    def _y(self, i: int) -> None:
        y = self.ylist
        if i == 3:
            self._test()
            return
        fy = ((y[i] - 1) * MULTINV) & M32
        ffy = ((fy - 1) * MULTINV) & M32
        for x0 in FIBER2[((ffy - (y[i - 2] & 0xFF000000)) & M32) >> 24]:
            yim1 = (fy - x0) & M32
            if ((ffy - MULTINV * x0 - (y[i - 2] & 0xFF000000)) & M32) <= MAXDIFF24 and yim1 >> 24 == y[i - 1] >> 24:
                y[i - 1] = yim1
                self.xlist[i] = x0
                self._y(i - 1)
                if self.solutions:
                    return

    def _test(self) -> None:
        x, y, z, p, c = self.xlist, self.ylist, self.zlist, self.plaintext, self.ciphertext
        start = self.index
        for i in range(5, 8):
            x[i] = (crc32(x[i - 1], p[start + i - 1]) & 0xFFFFFF00) | (x[i] & 0xFF)
        value = x[7]
        for i in range(6, 2, -1):
            value = crc32inv(value, p[start + i])
        y1_26_32 = (crc32inv(z[1], 0) ^ z[0]) << 24 & 0xFC000000
        if ((((y[3] - 1) * MULTINV - (value & 0xFF) - 1) * MULTINV - y1_26_32) & M32) > MAXDIFF26:
            return
        forward = Keys(x[7], y[7], z[7])
        forward.update(p[start + 7])
        for position in range(start + 8, len(p)):
            if c[self.offset + position] ^ forward.k() != p[position]:
                return
            forward.update(p[position])
        backward = Keys(value, y[3], z[3])
        for position in range(start + 2, -1, -1):
            backward.update_backward(c[self.offset + position])
            if c[self.offset + position] ^ backward.k() != p[position]:
                return
        for position in range(self.offset - 1, -1, -1):  # back to the state before the first header byte
            backward.update_backward(c[position])
        if self.extra:  # extra known bytes are ciphertext positions; check them by decrypting forward
            plain = backward.decrypt(c[:max(self.extra) + 1])
            if any(plain[position] != byte for position, byte in self.extra.items()):
                return
        self.solutions.append(backward)


def known_plaintext_attack(ciphertext: bytes, plaintext: bytes, offset: int, *, extra: dict[int, int] | None = None,
                           seconds: float = 120.0, max_candidates: int = 1 << 20,
                           workers: int | None = None,
                           phase_callback: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Recover the initial keys of an encrypted member (``ciphertext`` includes the 12-byte header).

    ``offset`` is the position of ``plaintext`` in ``ciphertext`` (12 = first data byte);
    ``extra`` maps further ciphertext positions to known plaintext bytes (e.g. the check byte at 11).
    """
    extra = dict(extra or {})
    if len(plaintext) < CONTIGUOUS or len(plaintext) + len(extra) < ATTACK_SIZE:
        return {"found": False, "reason": "not_enough_plaintext",
                "detail": f"need >= {ATTACK_SIZE} known bytes, >= {CONTIGUOUS} contiguous"}
    if offset < 0 or offset + len(plaintext) > len(ciphertext):
        return {"found": False, "reason": "plaintext_outside_ciphertext"}
    started = time.monotonic()
    deadline = started + seconds
    keystream = [p ^ ciphertext[offset + i] for i, p in enumerate(plaintext)]
    try:
        if phase_callback is not None:
            phase_callback("candidate-reduction")
        candidates, index = z_reduction(keystream, deadline)
    except BudgetExceeded:
        return {"found": False, "reason": "work_exceeds_budget", "stage": "z-reduction", "seconds": seconds}
    result: dict[str, Any] = {"candidates": len(candidates), "reduction_index": index}
    if len(candidates) > max_candidates:
        return {**result, "found": False, "reason": "work_exceeds_budget",
                "detail": "too many key2 candidates; supply more contiguous known plaintext"}
    jobs = max(1, min(workers or (os.cpu_count() or 1), 16))
    if phase_callback is not None:
        phase_callback("candidate-key-search")
    order = candidates.tolist()
    shards = [order[i::jobs] for i in range(jobs)]
    arguments = [(ciphertext, plaintext, offset, extra, index, shard, deadline) for shard in shards]
    tried, found, timed_out = 0, None, False
    if jobs == 1:
        tried, found = _attack_shard(arguments[0])
        elapsed = round(time.monotonic() - started, 1)
        if found:
            return {**result, "found": True, "keys": found, "tried": tried, "workers": jobs,
                    "seconds": elapsed}
        if time.monotonic() > deadline:
            return {**result, "found": False, "reason": "work_exceeds_budget", "stage": "key-search",
                    "tried": tried, "workers": jobs, "seconds": elapsed}
        return {**result, "found": False, "reason": "no_solution",
                "detail": "plaintext or offset is probably wrong", "workers": jobs, "seconds": elapsed}
    context = multiprocessing.get_context("spawn")
    with context.Pool(jobs) as pool:
        outcomes = []
        pending = pool.imap_unordered(_attack_shard, arguments)
        for _ in range(jobs):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                pool.terminate()
                break
            try:
                outcome = pending.next(timeout=remaining)
            except multiprocessing.TimeoutError:
                timed_out = True
                pool.terminate()
                break
            outcomes.append(outcome)
            if outcome[1] is not None:
                pool.terminate()  # one worker found the keys; stop the others now
                break
    for count, keys in outcomes:
        tried += count
        found = found or keys
    elapsed = round(time.monotonic() - started, 1)
    if found:
        return {**result, "found": True, "keys": found, "tried": tried, "workers": jobs, "seconds": elapsed}
    if timed_out or time.monotonic() > deadline:
        return {**result, "found": False, "reason": "work_exceeds_budget", "stage": "key-search",
                "tried": tried, "workers": jobs, "seconds": elapsed}
    return {**result, "found": False, "reason": "no_solution", "detail": "plaintext or offset is probably wrong",
            "workers": jobs, "seconds": elapsed}


def _attack_shard(arguments: tuple[Any, ...]) -> tuple[int, dict[str, str] | None]:
    ciphertext, plaintext, offset, extra, index, shard, deadline = arguments
    attack = _Attack(ciphertext, plaintext, offset, extra, index)
    for tried, candidate in enumerate(shard, 1):
        if time.monotonic() > deadline:
            return tried, None
        attack.carryout(candidate)
        if attack.solutions:
            return tried, attack.solutions[0].hex()
    return len(shard), None


# -- ZIP structure -------------------------------------------------------------------------------------
def members(data: bytes) -> list[dict[str, Any]]:
    """Local file entries (handles prefixes such as a PHP/ZIP polyglot)."""
    found: list[dict[str, Any]] = []
    position = 0
    while (position := data.find(b"PK\x03\x04", position)) >= 0 and len(found) < 64:
        if position + 30 > len(data):
            break
        (_sig, version, flags, method, mtime, mdate, crc, csize, usize, nlen,
         xlen) = struct.unpack_from("<IHHHHHIIIHH", data, position)
        name = data[position + 30:position + 30 + nlen].decode("utf-8", "replace")
        extra = data[position + 30 + nlen:position + 30 + nlen + xlen]
        start = position + 30 + nlen + xlen
        unix_mtime = None
        cursor = 0
        while cursor + 4 <= len(extra):
            tag, size = struct.unpack_from("<HH", extra, cursor)
            if tag == 0x5455 and size >= 5 and extra[cursor + 4] & 1:
                unix_mtime = struct.unpack_from("<I", extra, cursor + 5)[0]
            cursor += 4 + size
        found.append({"name": name, "offset": position, "data_offset": start, "flags": flags, "method": method,
                      "encrypted": bool(flags & 1), "data_descriptor": bool(flags & 8), "crc32": f"{crc:08x}",
                      "compressed_size": csize, "size": usize, "dos_time": mtime, "dos_date": mdate,
                      "unix_mtime": unix_mtime, "version": version})
        position = start + max(csize, 0)
    return found


def member_bytes(data: bytes, entry: dict[str, Any]) -> bytes:
    return data[entry["data_offset"]:entry["data_offset"] + entry["compressed_size"]]


def check_bytes(entry: dict[str, Any]) -> dict[int, int]:
    """Known plaintext of the encryption header: byte 11 (and 10) from CRC or DOS time."""
    if entry["data_descriptor"]:
        return {11: entry["dos_time"] >> 8 & 0xFF, 10: entry["dos_time"] & 0xFF}
    crc = int(entry["crc32"], 16)
    return {11: crc >> 24 & 0xFF, 10: crc >> 16 & 0xFF}


def zipcrypto_info(data: bytes) -> dict[str, Any]:
    entries = members(data)
    for entry in entries:
        if entry["encrypted"]:
            header = member_bytes(data, entry)[:12]
            entry["header_hex"] = header.hex()
            entry["infozip_leaked_rand_byte"] = header[0] if header else None
            entry["check_byte_11"] = check_bytes(entry)[11]
    encrypted = [entry for entry in entries if entry["encrypted"]]
    return {"members": entries, "encrypted_members": len(encrypted),
            "notes": [("Known plaintext attack: zipcrypto_attack needs >= 12 known bytes (8 contiguous) of one "
                      "member; header byte 11 is known (check byte)."),
                      ("Info-ZIP archives: header byte 0 of each member equals a rand() byte (Stay 2001); with "
                       "5+ members infozip_seed can recover the PRNG seed and all header bytes. Stay section 4 "
                       "uses the double-encryption stream-byte XOR constraints for key recovery.")]}


# -- Info-ZIP PRNG (Stay 2001, section 4) ------------------------------------------------------------
def _int32(values: np.ndarray) -> np.ndarray:
    wrapped = values & M32
    return np.where(wrapped >= 1 << 31, wrapped - (1 << 32), wrapped)


def glibc_rand_bytes(seeds: np.ndarray, count: int) -> np.ndarray:
    """(rand() >> 7) & 0xff for the first ``count`` glibc TYPE_3 outputs of each seed (vectorised).

    Mirrors __srandom_r exactly: ``int32_t word = seed``; each step computes
    16807*lo - 2836*hi in long arithmetic, truncates it to int32, then adds 2^31-1 if negative.
    Checked against the real glibc for small and large seeds (tests).
    """
    seeds = seeds.astype(np.uint64) & M32
    word = _int32(np.where(seeds == 0, 1, seeds).astype(np.int64))
    columns = [word & M32]
    for _ in range(1, 31):
        hi = np.trunc(word / 127773).astype(np.int64)
        lo = word - hi * 127773
        word = _int32(16807 * lo - 2836 * hi)
        word = np.where(word < 0, _int32(word + 2147483647), word)
        columns.append(word & M32)
    ring = [column.astype(np.uint32) for column in columns]
    ring += [ring[i - 31] for i in range(31, 34)]  # only the last 34 values are kept
    out = np.zeros((len(seeds), count), dtype=np.uint8)
    for i in range(34, 344 + count):
        nxt = ring[(i - 31) % 34] + ring[(i - 3) % 34]  # uint32 addition wraps mod 2^32
        ring[i % 34] = nxt
        if i >= 344:
            out[:, i - 344] = (nxt >> np.uint32(8)) & np.uint32(0xFF)  # (r >> 1) >> 7
    return out


def msvc_rand_bytes(seeds: np.ndarray, count: int) -> np.ndarray:
    state = seeds.astype(np.uint64) & M32
    out = np.zeros((len(seeds), count), dtype=np.uint8)
    for i in range(count):
        state = (state * 0x343FD + 0x269EC3) & M32
        out[:, i] = ((state >> np.uint64(16) & np.uint64(0x7FFF)) >> np.uint64(7)) & np.uint64(0xFF)
    return out


def _seed_space(time_from: int, time_to: int, salt: str, pid_bits: int) -> np.ndarray:
    times = np.arange(time_from, time_to + 1, dtype=np.uint64)
    if salt == "pi":  # crypt.c default when no ZCR_SEED2 is defined
        return np.unique((times ^ np.uint64(3141592654)) & np.uint64(M32))
    # tailor.h on Unix: ZCR_SEED2 = getpid(). time ^ pid covers every low pid_bits value.
    highs = np.unique(times >> np.uint64(pid_bits))
    low = np.arange(1 << pid_bits, dtype=np.uint64)
    return np.unique(((highs[:, None] << np.uint64(pid_bits)) | low[None, :]).ravel() & np.uint64(M32))


def infozip_seed(data: bytes, *, generator: str = "glibc", time_from: int | None = None, time_to: int | None = None,
                 salts: tuple[str, ...] = ("pid", "pi"), pid_bits: int = 22, stride: int = 10,
                 seconds: float = 120.0, chunk: int = 1 << 18) -> dict[str, Any]:
    """Find the srand() seed (time ^ getpid(), or time ^ PI) consistent with every member's leaked byte."""
    encrypted = [entry for entry in members(data) if entry["encrypted"]]
    if len(encrypted) < 3:
        return {"found": False, "reason": "too_few_members", "detail": "need >= 3 (Stay: 5) encrypted members"}
    if not 1 <= pid_bits <= 22:
        raise ValueError("pid_bits must be 1..22")
    leaked = np.array([member_bytes(data, entry)[0] for entry in encrypted], dtype=np.uint8)
    times = [entry["unix_mtime"] for entry in encrypted if entry["unix_mtime"]]
    if time_from is None or time_to is None:
        if not times:
            return {"found": False, "reason": "no_time_hint", "detail": "give time_from/time_to (unix seconds)"}
        time_from, time_to = min(times) - 120, max(times) + 3600
    if time_to - time_from > 31 * 86400:
        raise ValueError("time window limited to 31 days")
    count = stride * (len(encrypted) - 1) + 1
    produce = glibc_rand_bytes if generator == "glibc" else msvc_rand_bytes
    started, deadline = time.monotonic(), time.monotonic() + seconds
    tried = 0
    for salt in salts:
        space = _seed_space(time_from, time_to, salt, pid_bits)
        for begin in range(0, len(space), chunk):
            if time.monotonic() > deadline:
                return {"found": False, "reason": "work_exceeds_budget", "tried_seeds": tried,
                        "seconds": round(time.monotonic() - started, 1)}
            seeds = space[begin:begin + chunk]
            hits = np.nonzero((produce(seeds, count)[:, ::stride] == leaked).all(axis=1))[0]
            tried += len(seeds)
            if len(hits):
                seed = int(seeds[hits[0]])
                stream = produce(np.array([seed], dtype=np.uint64), stride * len(encrypted))[0]
                headers = [stream[i * stride:i * stride + 10].tobytes().hex() for i in range(len(encrypted))]
                return {"found": True, "generator": generator, "salt": salt, "seed": seed,
                        "members": len(encrypted), "matched_leaked_bytes": len(encrypted),
                        "random_header_bytes": headers, "tried_seeds": tried,
                        "seconds": round(time.monotonic() - started, 1),
                        "next": ("These are the rand() bytes r[i][0..9] of each member. Info-ZIP encrypted them "
                                 "twice, so they are not Biham-Kocher known plaintext. Stay section 4 specifically "
                                 "uses the resulting stream-byte XOR constraints for key recovery; its roughly "
                                 "2^39-cipher-step inverse search is not implemented in METIS and remains "
                                 "unavailable (work_exceeds_budget).")}
    return {"found": False, "reason": "no_seed_in_range", "tried_seeds": tried,
            "seconds": round(time.monotonic() - started, 1),
            "detail": "try another time window or generator, or the archive was not made by Info-ZIP"}


# -- decryption ----------------------------------------------------------------------------------------
def parse_keys(value: str) -> Keys:
    parts = [int(part, 16) for part in value.replace(" ", "").split(",")]
    if len(parts) != 3 or any(not 0 <= part <= M32 for part in parts):
        raise ValueError("keys are three hex words: x,y,z")
    return Keys(*parts)


def decrypt_member(data: bytes, name: str, keys: Keys) -> dict[str, Any]:
    entry = next((item for item in members(data) if item["name"] == name), None)
    if entry is None or not entry["encrypted"]:
        raise ValueError("no such encrypted member")
    plain = keys.decrypt(member_bytes(data, entry))
    header, body = plain[:12], plain[12:]
    if header[11] != check_bytes(entry)[11]:
        raise ValueError("check byte mismatch: wrong keys")
    if entry["method"] == 8:
        body = zlib.decompress(body, -15)
    elif entry["method"] != 0:
        raise ValueError("only stored and deflated members are supported")
    crc_ok = f"{zlib.crc32(body) & M32:08x}" == entry["crc32"]
    if not crc_ok:
        raise ValueError("CRC mismatch: wrong keys")
    return {"name": name, "size": len(body), "crc_ok": crc_ok, "plaintext": body}
