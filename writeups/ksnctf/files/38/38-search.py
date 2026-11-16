import sys, time
from multiprocessing import Pool
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

raw = open(sys.argv[1], 'rb').read()
assert raw[:8] == b'Salted__'
SALT, BODY = raw[8:16], raw[16:32]   # first cipher block is enough for a magic check
MAGIC = bytes.fromhex('ffd8ff')

def first_block_plain(pw):
    km = PBKDF2HMAC(algorithm=hashes.SHA256(), length=48, salt=SALT, iterations=10000).derive(pw)
    d = Cipher(algorithms.AES(km[:32]), modes.CBC(km[32:48])).decryptor()
    p = d.update(BODY) + d.finalize()
    return bytes(a ^ b for a, b in zip(p, km[32:48]))  # placeholder, replaced below

def check(pw):
    km = PBKDF2HMAC(algorithm=hashes.SHA256(), length=48, salt=SALT, iterations=10000).derive(pw)
    # AES-CBC single block decrypt: D(C1) xor IV
    d = Cipher(algorithms.AES(km[:32]), modes.ECB()).decryptor()
    p = d.update(BODY[:16]) + d.finalize()
    plain = bytes(a ^ b for a, b in zip(p, km[32:48]))
    return pw, plain[:4]

def main():
    cands = [bytes.fromhex(h) for h in ('ffd8ffe0', 'ffd8ffdb', 'ffd8ffee', 'ffd8ffe2')]
    t = time.time()
    for pw in cands:
        pw_, head = check(pw)
        print('cand', pw.hex(), head.hex(), flush=True)
    print('per-candidate seconds', round((time.time() - t) / len(cands), 4), flush=True)
    if len(sys.argv) > 2 and sys.argv[2] == 'exif':
        pws = []
        for hi in range(1, 256):
            for lo in range(1, 256):
                if hi in (0x0a, 0x0d) or lo in (0x0a, 0x0d):
                    continue
                pws.append(bytes([0xff, 0xd8, 0xff, 0xe1, hi, lo, 0x45, 0x78, 0x69, 0x66]))
        with Pool() as pool:
            for pw, head in pool.imap_unordered(check, pws, chunksize=64):
                if head[:3] == MAGIC:
                    print('HIT', pw.hex(), head.hex(), flush=True)
        print('exif scan done', len(pws), flush=True)

if __name__ == '__main__':
    main()
