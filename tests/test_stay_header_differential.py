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
