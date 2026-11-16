"""Pure-python sha512crypt ($6$), per Drepper's SHA-crypt spec, no libc needed."""
import hashlib

B64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

ROUNDS_DEFAULT = 5000
ROUNDS_MIN = 1000
ROUNDS_MAX = 999999999

PERM = [
    (0, 21, 42), (22, 43, 1), (44, 2, 23), (3, 24, 45), (25, 46, 4),
    (47, 5, 26), (6, 27, 48), (28, 49, 7), (50, 8, 29), (9, 30, 51),
    (31, 52, 10), (53, 11, 32), (12, 33, 54), (34, 55, 13), (56, 14, 35),
    (15, 36, 57), (37, 58, 16), (59, 17, 38), (18, 39, 60), (40, 61, 19),
    (62, 20, 41),
]


def _b64_from_24bit(b2, b1, b0, n):
    w = (b2 << 16) | (b1 << 8) | b0
    out = []
    for _ in range(n):
        out.append(B64[w & 0x3F])
        w >>= 6
    return "".join(out)


def sha512_crypt(password: str, salt: str, rounds: int = ROUNDS_DEFAULT) -> str:
    pw = password.encode()
    s = salt.encode()

    A = hashlib.sha512()
    A.update(pw)
    A.update(s)

    B = hashlib.sha512()
    B.update(pw)
    B.update(s)
    B.update(pw)
    digest_b = B.digest()

    plen = len(pw)
    i = plen
    while i > 64:
        A.update(digest_b)
        i -= 64
    A.update(digest_b[:i])

    i = plen
    while i > 0:
        if i & 1:
            A.update(digest_b)
        else:
            A.update(pw)
        i >>= 1

    digest_a = A.digest()

    # DP
    DP = hashlib.sha512()
    for _ in range(plen):
        DP.update(pw)
    digest_dp = DP.digest()
    # produce P of length plen
    p_bytes = (digest_dp * (plen // 64 + 1))[:plen]

    # DS
    slen = len(s)
    DS = hashlib.sha512()
    count_ds = 16 + digest_a[0]
    for _ in range(count_ds):
        DS.update(s)
    digest_ds = DS.digest()
    s_bytes = (digest_ds * (slen // 64 + 1))[:slen]

    for r in range(rounds):
        C = hashlib.sha512()
        if r & 1:
            C.update(p_bytes)
        else:
            C.update(digest_a)
        if r % 3 != 0:
            C.update(s_bytes)
        if r % 7 != 0:
            C.update(p_bytes)
        if r & 1:
            C.update(digest_a)
        else:
            C.update(p_bytes)
        digest_a = C.digest()

    out = []
    for a, b, c in PERM:
        out.append(_b64_from_24bit(digest_a[a], digest_a[b], digest_a[c], 4))
    out.append(_b64_from_24bit(0, 0, digest_a[63], 2))
    return "".join(out)


def parse_and_verify(full_hash: str, password: str) -> bool:
    # full_hash like $6$salt$hash  or $6$rounds=N$salt$hash
    parts = full_hash.split("$")
    # parts: ['', '6', 'salt', 'hash']  or ['', '6', 'rounds=N', 'salt', 'hash']
    assert parts[1] == "6"
    if parts[2].startswith("rounds="):
        rounds = int(parts[2][len("rounds="):])
        salt = parts[3]
        expected = parts[4]
    else:
        rounds = ROUNDS_DEFAULT
        salt = parts[2]
        expected = parts[3]
    salt = salt[:16]
    computed = sha512_crypt(password, salt, rounds)
    return computed == expected


if __name__ == "__main__":
    # self-test against known spec vectors
    tests = [
        ("Hello world!", "saltstring", 5000,
         "svn8UoSVapNtMuq1ukKS4tPQd8iKwSMHWjl/O817G3uBnIFNjnQJuesI68u4OTLiBFdcbYEdFCoEOfaS35inz1"),
        ("Hello world!", "saltstringsaltstring", 10000,
         "OW1/O6BYHV6BcXZu8QVeXbDWra3Oeqh0sbHbbMCVNSnCM/UrjmM0Dp8vOuZeHBy/YTEmtWuGOxx7XBVcVosE1"),
        ("This is just a test", "toolongsaltstring", 5000,
         "lQ8jolhgVRVhY4b5pZKaysCLi0QBxGoNeKQzQ3glMhwllF7oGDZxUhx1yxRVmNFzAbLOtiZSFzQIV+lMRcM2."),
    ]
    ok = True
    for pw, salt, rounds, expected in tests:
        got = sha512_crypt(pw, salt[:16], rounds)
        status = "OK" if got == expected else "FAIL"
        if got != expected:
            ok = False
        print(status, pw, salt, rounds)
        print("  got     ", got)
        print("  expected", expected)
    print("ALL_OK" if ok else "SOME_FAILED")
