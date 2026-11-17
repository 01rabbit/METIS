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
