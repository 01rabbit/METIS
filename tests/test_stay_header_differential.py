"""Synthetic checks for the first two Info-ZIP double-encrypted header bytes.

These verify one forward relation used by Stay section 4. They do not test
the paper's inverse key-recovery search.
"""
import random

MASK32 = 0xFFFFFFFF
MULT = 0x08088405


def _crc_update(state: int, byte: int) -> int:
    """Bitwise ZIP CRC update, independent of METIS's precomputed tables."""
    state ^= byte
    for _ in range(8):
        state = (state >> 1) ^ (0xEDB88320 if state & 1 else 0)
    return state & MASK32


def _stream_byte(key2: int) -> int:
    value = (key2 & 0xFFFF) | 2
    return (value * (value ^ 1) >> 8) & 0xFF


def _update(keys: tuple[int, int, int], plaintext: int) -> tuple[int, int, int]:
    key0, key1, key2 = keys
    key0 = _crc_update(key0, plaintext)
    key1 = ((key1 + (key0 & 0xFF)) * MULT + 1) & MASK32
    key2 = _crc_update(key2, key1 >> 24)
    return key0, key1, key2


def _encrypt(data: bytes, initial: tuple[int, int, int]) -> bytes:
    keys = initial
    ciphertext = bytearray()
    for plaintext in data:
        ciphertext.append(plaintext ^ _stream_byte(keys[2]))
        keys = _update(keys, plaintext)
    return bytes(ciphertext)


def _second_byte_differential(random_first: int,
                              initial: tuple[int, int, int]) -> int:
    """Predict C[1] XOR R[1] from Stay's two-pass header relation."""
    key0, key1, key2 = initial
    first_stream = _stream_byte(key2)
    second_pass_first_plaintext = random_first ^ first_stream

    first_key0_low = _crc_update(key0, random_first) & 0xFF
    second_key0_low = _crc_update(key0, second_pass_first_plaintext) & 0xFF
    first_key1 = ((key1 + first_key0_low) * MULT + 1) & MASK32
    second_key1 = ((key1 + second_key0_low) * MULT + 1) & MASK32
    first_key2 = _crc_update(key2, first_key1 >> 24)
    second_key2 = _crc_update(key2, second_key1 >> 24)
    return _stream_byte(first_key2) ^ _stream_byte(second_key2)


def test_stay_first_header_cancellation_and_second_byte_relation() -> None:
    rng = random.Random(20261118)
    for _ in range(10_000):
        initial = (rng.getrandbits(32), rng.getrandbits(32), rng.getrandbits(32))
        random_header = bytes(rng.getrandbits(8) for _ in range(10))

        first_pass = _encrypt(random_header, initial)
        stored_header = _encrypt(first_pass, initial)

        # The first output cancels because both passes start at the same state.
        assert stored_header[0] == random_header[0]
        # The second output exposes the differential used in Stay section 4.
        assert (stored_header[1] ^ random_header[1]) == _second_byte_differential(
            random_header[0], initial)


def test_stay_stage2_third_byte_predictor_matches_planted_full_states() -> None:
    from metis.core.ctf_zipcrypto import _stay_predict_third_byte_difference

    rng = random.Random(20261119)
    wrong_q8_changed = False
    wrong_carry_changed = False
    for _ in range(10_000):
        initial = (rng.getrandbits(32), rng.getrandbits(32), rng.getrandbits(32))
        random_header = bytes(rng.getrandbits(8) for _ in range(10))
        x0, y0, z0 = initial
        product1 = y0 * MULT & MASK32
        product2 = y0 * MULT * MULT & MASK32
        assert ((product1 * MULT) & MASK32) >> 24 == product2 >> 24
        crc0 = _crc_update(x0, 0)
        crc2 = _crc_update(z0, 0)
        first_stream = _stream_byte(z0)

        first_pass = _encrypt(random_header, initial)
        stored_header = _encrypt(first_pass, initial)
        def carry_after_two(p0: int, p1: int, initial_key0: int,
                            first_product: int, second_product: int) -> tuple[int, int]:
            key0_1 = _crc_update(initial_key0, p0)
            a1 = key0_1 & 0xFF
            first_offset = a1 * MULT + 1
            carry1 = ((first_product & 0xFFFFFF) + (first_offset & 0xFFFFFF)) >> 24
            key0_2 = _crc_update(key0_1, p1)
            a2 = key0_2 & 0xFF
            total2 = a1 * MULT * MULT + MULT + a2 * MULT + 1
            carry2 = ((second_product & 0xFFFFFF) + (total2 & 0xFFFFFF)) >> 24
            return carry1, carry2

        stage1_carry1, stage2_carry1 = carry_after_two(
            random_header[0], random_header[1], x0, product1, product2)
        # The second pass consumes the first pass's ciphertext bytes as plaintext.
        stage1_carry2, stage2_carry2 = carry_after_two(
            first_pass[0], first_pass[1], x0, product1, product2)
        predicted = _stay_predict_third_byte_difference(
            random_header[0], random_header[1], first_stream, crc0 & 0xFFFF,
            product1 >> 24, crc2 & 0xFFFFFF, stage1_carry1, stage1_carry2,
            product2 >> 24, stage2_carry1, stage2_carry2)
        assert predicted == (stored_header[2] ^ random_header[2])

        wrong_q8 = _stay_predict_third_byte_difference(
            random_header[0], random_header[1], first_stream, crc0 & 0xFFFF,
            product1 >> 24, crc2 & 0xFFFFFF, stage1_carry1, stage1_carry2,
            (product2 >> 24) ^ 1, stage2_carry1, stage2_carry2)
        wrong_q8_changed |= wrong_q8 != predicted
        wrong_carry = _stay_predict_third_byte_difference(
            random_header[0], random_header[1], first_stream, crc0 & 0xFFFF,
            product1 >> 24, crc2 & 0xFFFFFF, stage1_carry1, stage1_carry2,
            product2 >> 24, stage2_carry1 ^ 1, stage2_carry2)
        wrong_carry_changed |= wrong_carry != predicted

    assert wrong_q8_changed and wrong_carry_changed


def test_stay_q8_interval_mask_matches_exhaustive_small_word_oracle() -> None:
    from metis.core.ctf_zipcrypto import MULT, _stay_q8_carry_masks

    rng = random.Random(20261120)
    bits = 5
    low_limit = 1 << bits
    for _ in range(500):
        product_high = rng.randrange(256)
        lower = rng.randrange(low_limit)
        upper = rng.randrange(lower, low_limit)
        addends = tuple(rng.randrange(low_limit) for _ in range(3))
        actual = _stay_q8_carry_masks((product_high, lower, upper), addends, bits=bits)
        expected: dict[int, tuple[int, ...]] = {}
        for low in range(lower, upper + 1):
            product = (product_high << bits) | low
            residue = (product * MULT) & ((1 << (bits + 8)) - 1)
            q8 = residue >> bits
            masks = list(expected.get(q8, (0, 0, 0)))
            low_residue = residue & (low_limit - 1)
            for index, addend in enumerate(addends):
                carry = int(low_residue + addend >= low_limit)
                masks[index] |= 1 << carry
            expected[q8] = tuple(masks)
        assert actual == expected


def test_stay_reduced_subspace_filter_matches_exhaustive_forward_oracle() -> None:
    """A small candidate filter must retain exactly the direct-oracle survivors."""
    rng = random.Random(98_765)
    bases = [0x13570000, 0x23456789, 0x34500090]
    variable_bits = ((0, (8, 9, 10, 11)), (1, (24, 25, 26, 27)), (2, (8, 9, 10, 11)))
    planted = (bases[0] | (1 << 8) | (1 << 10) | (1 << 11),
               bases[1] | (1 << 24) | (1 << 26),
               bases[2] | (1 << 9) | (1 << 10) | (1 << 11))
    headers = [bytes((rng.randrange(256), rng.randrange(256))) for _ in range(5)]
    observed = [
        _encrypt(_encrypt(header, planted), planted)[1] ^ header[1]
        for header in headers
    ]

    candidates = []
    for mask in range(1 << 12):
        state = bases.copy()
        bit_index = 0
        for state_index, positions in variable_bits:
            for position in positions:
                if mask & (1 << bit_index):
                    state[state_index] |= 1 << position
                bit_index += 1
        candidates.append(tuple(state))

    for index, observations in enumerate((observed, [observed[0] ^ 1, *observed[1:]])):
        filtered = {
            state for state in candidates
            if all(_second_byte_differential(header[0], state) == value
                   for header, value in zip(headers, observations, strict=True))
        }
        exhaustive = {
            state for state in candidates
            if all(_encrypt(_encrypt(header, state), state)[1] ^ header[1] == value
                   for header, value in zip(headers, observations, strict=True))
        }
        assert filtered == exhaustive
        if index == 0:
            assert planted in filtered
        else:
            assert planted not in filtered


def test_stay_carry_interval_matches_exhaustive_low_word_oracle() -> None:
    """Carry guesses must select exactly one contiguous low-word interval."""
    from metis.core.ctf_zipcrypto import _stay_carry_interval

    rng = random.Random(20_261_118)
    bits = 8
    modulus = 1 << bits
    for _ in range(250):
        planted = rng.randrange(modulus)
        addends = tuple(rng.randrange(modulus) for _ in range(10))
        carries = tuple(int(planted + addend >= modulus) for addend in addends)
        expected = {
            candidate for candidate in range(modulus)
            if tuple(int(candidate + addend >= modulus) for addend in addends) == carries
        }
        interval = _stay_carry_interval(addends, carries, bits=bits)
        assert expected
        assert interval is not None
        assert set(range(interval[0], interval[1] + 1)) == expected
        assert interval[0] <= planted <= interval[1]


def test_stay_carry_interval_handles_exact_boundaries_and_bad_guesses() -> None:
    import pytest

    from metis.core.ctf_zipcrypto import _stay_carry_interval

    assert _stay_carry_interval((0,), (0,), bits=8) == (0, 255)
    assert _stay_carry_interval((0,), (1,), bits=8) is None
    assert _stay_carry_interval((255,), (0,), bits=8) == (0, 0)
    assert _stay_carry_interval((255,), (1,), bits=8) == (1, 255)
    assert _stay_carry_interval((200, 200), (1, 0), bits=8) is None
    with pytest.raises(ValueError, match="zero or one"):
        _stay_carry_interval((1,), (2,), bits=8)
    with pytest.raises(ValueError, match="word width"):
        _stay_carry_interval((1,), (0,), bits=True)
    with pytest.raises(ValueError, match="word width"):
        _stay_carry_interval((1,), (0,), bits=1.5)  # type: ignore[arg-type]


def test_stay_key1_product_lifting_matches_reduced_width_exhaustive_oracle() -> None:
    """Carry pruning and inverse multiplication must retain exactly the direct survivors."""
    from metis.core.ctf_zipcrypto import (
        MULT,
        _stay_key1_product_interval,
        _stay_lift_key1_candidates,
    )

    rng = random.Random(0x51A7)
    bits = 8
    word_mask = (1 << (bits + 8)) - 1
    for _ in range(100):
        planted = rng.randrange(word_mask + 1)
        addends = tuple(rng.randrange(1 << bits) for _ in range(6))
        product = planted * MULT & word_mask
        carries = tuple(
            int((product & ((1 << bits) - 1))
                + (addend * MULT + 1 & ((1 << bits) - 1)) >= 1 << bits)
            for addend in addends
        )
        top_bytes = tuple(
            ((product + addend * MULT + 1) & word_mask) >> bits
            for addend in addends
        )
        interval = _stay_key1_product_interval(addends, top_bytes, carries, bits=bits)
        assert interval is not None
        lifted = set(_stay_lift_key1_candidates(interval, bits=bits))
        direct = {
            key1 for key1 in range(word_mask + 1)
            if all(
                ((key1 * MULT + addend * MULT + 1) & word_mask) >> bits == top
                and int(((key1 * MULT) & ((1 << bits) - 1))
                        + ((addend * MULT + 1) & ((1 << bits) - 1)) >= 1 << bits) == carry
                for addend, top, carry in zip(addends, top_bytes, carries, strict=True)
            )
        }
        assert lifted == direct
        assert planted in lifted

    inconsistent = (top_bytes[0] ^ 1, *top_bytes[1:])
    assert _stay_key1_product_interval(addends, inconsistent, carries, bits=bits) is None


def test_stay_partial_guess_filter_matches_full_state_forward_oracle() -> None:
    """The partial 23-bit state and carry guesses predict the exact header differential."""
    from metis.core.ctf_zipcrypto import (
        CRCTAB,
        M32,
        MULT,
        _stay_predict_second_byte_difference,
    )

    rng = random.Random(0x40B17)
    for _ in range(10_000):
        initial = tuple(rng.getrandbits(32) for _ in range(3))
        random_first = rng.randrange(256)
        key0_crc_low = _crc_update(initial[0], 0) & 0xFF
        product = initial[1] * MULT & M32
        key1_product_high = product >> 24
        key2_crc_bits_2_15 = _crc_update(initial[2], 0) & 0xFFFC
        first_stream = _stream_byte(initial[2])
        first_low = _crc_update(initial[0], random_first) & 0xFF
        second_low = _crc_update(initial[0], random_first ^ first_stream) & 0xFF
        first_offset = first_low * MULT + 1
        second_offset = second_low * MULT + 1
        first_carry = int((product & 0xFFFFFF) + (first_offset & 0xFFFFFF) >= 1 << 24)
        second_carry = int((product & 0xFFFFFF) + (second_offset & 0xFFFFFF) >= 1 << 24)

        predicted = _stay_predict_second_byte_difference(
            random_first, first_stream, key0_crc_low, key1_product_high,
            key2_crc_bits_2_15, first_carry, second_carry)
        assert predicted == _second_byte_differential(random_first, initial)

    # The CRC table is used by the production recurrence; this independent
    # check catches a mismatched table index in the partial-state equation.
    assert all(CRCTAB[value] == _crc_update(0, value) for value in range(256))


def test_stay_first_stage_carry_masks_retain_full_state_guesses() -> None:
    """The first-file fixed carries and later per-file branches retain planted states."""
    import pytest

    from metis.core.ctf_zipcrypto import (
        M32,
        MULT,
        _stay_first_stage_carry_masks,
        _stay_key1_product_interval,
        _stay_lift_key1_candidates,
    )

    rng = random.Random(0xF17E)
    for _ in range(100):
        initial = (rng.getrandbits(32), rng.getrandbits(32), rng.getrandbits(32))
        product = initial[1] * MULT & M32
        first_stream = _stream_byte(initial[2])
        random_firsts = tuple(rng.randrange(256) for _ in range(7))
        random_seconds = tuple(rng.randrange(256) for _ in range(7))
        observed = tuple(
            _encrypt(_encrypt(bytes((first, second)), initial), initial)[1] ^ second
            for first, second in zip(random_firsts, random_seconds, strict=True)
        )
        carries = []
        addends = []
        top_bytes = []
        for first in random_firsts:
            second_pass_first = first ^ first_stream
            first_low = _crc_update(initial[0], first) & 0xFF
            second_low = _crc_update(initial[0], second_pass_first) & 0xFF
            first_offset = first_low * MULT + 1
            second_offset = second_low * MULT + 1
            addends.extend((first_low, second_low))
            top_bytes.extend((
                ((initial[1] + first_low) * MULT + 1 & M32) >> 24,
                ((initial[1] + second_low) * MULT + 1 & M32) >> 24,
            ))
            carries.append((
                int((product & 0xFFFFFF) + (first_offset & 0xFFFFFF) >= 1 << 24),
                int((product & 0xFFFFFF) + (second_offset & 0xFFFFFF) >= 1 << 24),
            ))

        masks = _stay_first_stage_carry_masks(
            random_firsts, observed, first_stream, _crc_update(initial[0], 0) & 0xFF,
            product >> 24, _crc_update(initial[2], 0) & 0xFFFC, *carries[0])
        assert masks is not None and len(masks) == len(random_firsts)
        assert masks[0] == 1 << (carries[0][0] * 2 + carries[0][1])
        for mask, (carry1, carry2) in zip(masks[1:], carries[1:], strict=True):
            assert mask & (1 << (carry1 * 2 + carry2))

        flat_carries = tuple(carry for pair in carries for carry in pair)
        interval = _stay_key1_product_interval(tuple(addends), tuple(top_bytes), flat_carries)
        assert interval is not None
        assert initial[1] in set(_stay_lift_key1_candidates(interval))

    with pytest.raises(ValueError, match="five or more"):
        _stay_first_stage_carry_masks((0, 1, 2, 3), (0, 1, 2, 3), 0, 0, 0, 0, 0, 0)


def test_stay_first_stage_packed_guess_retains_full_state() -> None:
    """The paper's 40 guessed bits map to a full-state candidate without bit loss."""
    import pytest

    from metis.core.ctf_zipcrypto import (
        M32,
        MULT,
        _stay_first_stage_candidate,
    )

    rng = random.Random(0x40_40)
    for _ in range(100):
        initial = (rng.getrandbits(32), rng.getrandbits(32), rng.getrandbits(32))
        first_stream = _stream_byte(initial[2])
        key0_crc_low = _crc_update(initial[0], 0) & 0xFF
        product = initial[1] * MULT & M32
        key2_crc = _crc_update(initial[2], 0) & 0xFFFC
        random_firsts = tuple(rng.randrange(256) for _ in range(7))
        random_seconds = tuple(rng.randrange(256) for _ in range(7))
        observed = tuple(
            _encrypt(_encrypt(bytes((first, second)), initial), initial)[1] ^ second
            for first, second in zip(random_firsts, random_seconds, strict=True)
        )

        first_low = _crc_update(initial[0], random_firsts[0]) & 0xFF
        second_low = _crc_update(initial[0], random_firsts[0] ^ first_stream) & 0xFF
        first_carry = int((product & 0xFFFFFF) + (first_low * MULT + 1 & 0xFFFFFF) >= 1 << 24)
        second_carry = int((product & 0xFFFFFF) + (second_low * MULT + 1 & 0xFFFFFF) >= 1 << 24)
        index = (
            first_stream | key0_crc_low << 8 | (product >> 24) << 16
            | first_carry << 24 | (key2_crc >> 10) << 25
            | (key2_crc >> 2 & 0xFF) << 31 | second_carry << 39
        )

        masks = _stay_first_stage_candidate(index, random_firsts, observed)
        assert masks is not None
        assert masks[0] == 1 << (first_carry * 2 + second_carry)
        for member_index, first in enumerate(random_firsts):
            pass_first = _crc_update(initial[0], first) & 0xFF
            pass_second = _crc_update(initial[0], first ^ first_stream) & 0xFF
            carry_first = int((product & 0xFFFFFF) + (pass_first * MULT + 1 & 0xFFFFFF) >= 1 << 24)
            carry_second = int((product & 0xFFFFFF) + (pass_second * MULT + 1 & 0xFFFFFF) >= 1 << 24)
            assert masks[member_index] & (1 << (carry_first * 2 + carry_second))

    with pytest.raises(ValueError, match="40-bit"):
        _stay_first_stage_candidate(1 << 40, (0, 1, 2, 3, 4), (0, 1, 2, 3, 4))


def test_stay_first_stage_shared_carry_intervals_retain_planted_key1() -> None:
    from metis.core.ctf_zipcrypto import (
        M32,
        MULT,
        _stay_first_stage_candidate,
        _stay_first_stage_key1_intervals,
        _stay_q8_carry_masks,
    )

    rng = random.Random(0x11F7)
    for _ in range(30):
        initial = (rng.getrandbits(32), rng.getrandbits(32), rng.getrandbits(32))
        first_stream = _stream_byte(initial[2])
        key0_crc_low = _crc_update(initial[0], 0) & 0xFF
        product = initial[1] * MULT & M32
        key2_crc = _crc_update(initial[2], 0) & 0xFFFC
        random_firsts = tuple(rng.randrange(256) for _ in range(7))
        random_seconds = tuple(rng.randrange(256) for _ in range(7))
        observed = tuple(
            _encrypt(_encrypt(bytes((first, second)), initial), initial)[1] ^ second
            for first, second in zip(random_firsts, random_seconds, strict=True)
        )
        first_low = _crc_update(initial[0], random_firsts[0]) & 0xFF
        second_low = _crc_update(initial[0], random_firsts[0] ^ first_stream) & 0xFF
        carry_first = int((product & 0xFFFFFF) + ((first_low * MULT + 1) & 0xFFFFFF) >= 1 << 24)
        carry_second = int((product & 0xFFFFFF) + ((second_low * MULT + 1) & 0xFFFFFF) >= 1 << 24)
        index = (
            first_stream | key0_crc_low << 8 | (product >> 24) << 16
            | carry_first << 24 | (key2_crc >> 10) << 25
            | (key2_crc >> 2 & 0xFF) << 31 | carry_second << 39
        )
        masks = _stay_first_stage_candidate(index, random_firsts, observed)
        assert masks is not None
        true_pairs = []
        for first in random_firsts:
            low1 = _crc_update(initial[0], first) & 0xFF
            low2 = _crc_update(initial[0], first ^ first_stream) & 0xFF
            carry1 = int((product & 0xFFFFFF) + ((low1 * MULT + 1) & 0xFFFFFF) >= 1 << 24)
            carry2 = int((product & 0xFFFFFF) + ((low2 * MULT + 1) & 0xFFFFFF) >= 1 << 24)
            true_pairs.append(carry1 * 2 + carry2)
        intervals = tuple(_stay_first_stage_key1_intervals(index, masks, random_firsts))
        assert any(pairs == tuple(true_pairs)
                   and interval[0] == (product >> 24)
                   and interval[1] <= (product & 0xFFFFFF) <= interval[2]
                   for interval, pairs in intervals)
        true_q8 = ((product * MULT) & M32) >> 24
        true_second_carries = []
        second_addends = []
        for first, second in zip(random_firsts, random_seconds, strict=True):
            first_pass = _encrypt(bytes((first, second)), initial)
            for plaintext_pair in ((first, second), first_pass):
                after_first = _update(initial, plaintext_pair[0])
                after_second = _update(after_first, plaintext_pair[1])
                addend = ((after_first[0] & 0xFF) * MULT * MULT + MULT
                          + (after_second[0] & 0xFF) * MULT + 1) & 0xFFFFFF
                second_addends.append(addend)
                true_second_carries.append(
                    int(((product * MULT) & 0xFFFFFF) + addend >= 1 << 24))
        planted_state_retained = False
        for interval, pairs in intervals:
            if pairs != tuple(true_pairs):
                continue
            carry_masks = _stay_q8_carry_masks(interval, tuple(second_addends)).get(true_q8)
            if (carry_masks is not None
                    and all(mask & (1 << carry) for mask, carry in zip(
                        carry_masks, true_second_carries, strict=True))):
                planted_state_retained = True
                break
        assert planted_state_retained


def test_stay_stage2_two_update_key1_formula_matches_full_recurrence() -> None:
    """The proposed Stage 2 key1 high-byte decomposition matches the cipher."""
    from metis.core.ctf_zipcrypto import MULT

    rng = random.Random(0xD4652819)
    multiplier_squared = MULT * MULT & MASK32
    for _ in range(10_000):
        initial = (rng.getrandbits(32), rng.getrandbits(32), rng.getrandbits(32))
        first, second = rng.randrange(256), rng.randrange(256)
        after_first = _update(initial, first)
        after_second = _update(after_first, second)
        addend_first = after_first[0] & 0xFF
        addend_second = after_second[0] & 0xFF

        q = initial[1] * multiplier_squared & MASK32
        t = (addend_first * multiplier_squared + MULT
             + addend_second * MULT + 1) & MASK32
        assert (q + t) & MASK32 == after_second[1]

        carry = int((q & 0xFFFFFF) + (t & 0xFFFFFF) >= 1 << 24)
        predicted_high = ((q >> 24) + (t >> 24) + carry) & 0xFF
        assert predicted_high == after_second[1] >> 24


def test_stay_first_stage_scan_chunk_resumes_without_skipping_candidate() -> None:
    """Adjacent bounded ranges resume at the cursor and retain the planted guess."""
    from metis.core.ctf_zipcrypto import (
        M32,
        MULT,
        _stay_first_stage_candidate,
        _stay_first_stage_scan_chunk,
        _stay_first_stage_scan_parallel,
    )

    rng = random.Random(0x5CA1)
    initial = (rng.getrandbits(32), rng.getrandbits(32), rng.getrandbits(32))
    first_stream = _stream_byte(initial[2])
    key0_crc_low = _crc_update(initial[0], 0) & 0xFF
    product = initial[1] * MULT & M32
    key2_crc = _crc_update(initial[2], 0) & 0xFFFC
    random_firsts = tuple(rng.randrange(256) for _ in range(5))
    random_seconds = tuple(rng.randrange(256) for _ in range(5))
    observed = tuple(
        _encrypt(_encrypt(bytes((first, second)), initial), initial)[1] ^ second
        for first, second in zip(random_firsts, random_seconds, strict=True)
    )
    low_first = _crc_update(initial[0], random_firsts[0]) & 0xFF
    low_second = _crc_update(initial[0], random_firsts[0] ^ first_stream) & 0xFF
    carry_first = int((product & 0xFFFFFF) + (low_first * MULT + 1 & 0xFFFFFF) >= 1 << 24)
    carry_second = int((product & 0xFFFFFF) + (low_second * MULT + 1 & 0xFFFFFF) >= 1 << 24)
    index = (
        first_stream | key0_crc_low << 8 | (product >> 24) << 16
        | carry_first << 24 | (key2_crc >> 10) << 25
        | (key2_crc >> 2 & 0xFF) << 31 | carry_second << 39
    )
    assert index > 0

    first = _stay_first_stage_scan_chunk(
        random_firsts, observed, index - 1, index + 1, max_candidates=1)
    assert first["next_index"] == index
    assert first["complete"] is False
    second = _stay_first_stage_scan_chunk(
        random_firsts, observed, first["next_index"], index + 1, max_candidates=1)
    assert second["next_index"] == index + 1
    assert second["complete"] is True
    assert second["hits"] and second["hits"][0][0] == index

    vector_chunk = _stay_first_stage_scan_chunk(
        random_firsts, observed, index, index + 256, max_candidates=256)
    scalar_hits = tuple(
        (candidate, masks)
        for candidate in range(index, index + 256)
        if (masks := _stay_first_stage_candidate(candidate, random_firsts, observed)) is not None
    )
    assert vector_chunk["complete"] is True
    assert vector_chunk["hits"] == scalar_hits
    parallel_chunk = _stay_first_stage_scan_parallel(
        random_firsts, observed, index, index + 256,
        max_candidates=256, seconds=30, max_hits=4096, workers=4)
    assert parallel_chunk["complete"] is True
    assert parallel_chunk["hits"] == scalar_hits

    capped = _stay_first_stage_scan_chunk(
        random_firsts, observed, index, index + 256, max_candidates=256, max_hits=1)
    assert capped["hits"] == scalar_hits[:1]
    assert capped["next_index"] == scalar_hits[0][0] + 1
    remainder = _stay_first_stage_scan_chunk(
        random_firsts, observed, capped["next_index"], index + 256,
        max_candidates=256, max_hits=4096)
    assert remainder["hits"] == scalar_hits[1:]


def test_stay_infozip_fixture_second_byte_relation_and_mutated_seed_negative() -> None:
    """Check the shared second-byte relation and reject altered PRNG observations."""
    from pathlib import Path

    import numpy as np

    from metis.core import ctf_zipcrypto as zc

    archive = (Path(__file__).parent / "fixtures" / "infozip-glibc-vector.zip").read_bytes()
    recovered = zc.infozip_seed(archive, seconds=120)
    assert recovered["found"] and recovered["matched_leaked_bytes"] == 7
    members = [entry for entry in zc.members(archive) if entry["encrypted"]]
    random_headers = [bytes.fromhex(value) for value in recovered["random_header_bytes"]]
    seed = recovered["seed"]
    keys = zc.Keys.from_password(b"testpass")
    initial = (keys.x, keys.y, keys.z)

    def jointly_consistent(headers: list[bytes]) -> bool:
        return len(headers) == len(members) and all(
            zc.member_bytes(archive, entry)[0] == header[0]
            and
            (zc.member_bytes(archive, entry)[1] ^ header[1])
            == _second_byte_differential(header[0], initial)
            for entry, header in zip(members, headers, strict=True)
        )

    assert jointly_consistent(random_headers)

    # Preserve each observed first byte while changing a second-byte PRNG observation.
    # This specifically exercises rejection after the first-byte prefilter.
    altered_observations = [bytes((header[0], header[1] ^ 1, *header[2:]))
                            for header in random_headers]
    assert not jointly_consistent(altered_observations)

    # Also check one arbitrary different seed; this is not a search over all
    # alternative seeds that happen to pass the first-byte prefilter.
    wrong_stream = zc.glibc_rand_bytes(np.array([seed ^ 1], dtype=np.uint64), 70)[0]
    wrong_headers = [bytes(wrong_stream[i * 10:i * 10 + 10]) for i in range(len(members))]
    assert not jointly_consistent(wrong_headers)
