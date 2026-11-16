import sys, hashlib
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ENC = sys.argv[1]
canned = open(sys.argv[2], 'rb').read()
raw = open(ENC, 'rb').read()
assert raw[:8] == b'Salted__', 'no Salted__ header'
salt, body = raw[8:16], raw[16:]

def openssl_file_pass(data):
    # OpenSSL 1.1.1 -pass file: reads one line, C string stops at NUL
    line = data[:8191].split(b'\n', 1)[0]
    return line.split(b'\x00', 1)[0].split(b'\r', 1)[0]

def dec(pw):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=48, salt=salt, iterations=10000)
    km = kdf.derive(pw)
    key, iv = km[:32], km[32:48]
    d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    p = d.update(body) + d.finalize()
    try:
        return padding.PKCS7(128).unpadder().update(p) + b''
    except Exception:
        return None

cands = {'canned_prefix': openssl_file_pass(canned)}
for name, pw in cands.items():
    out = dec(pw)
    print(name, len(pw), pw.hex(), 'unpad_ok' if out else 'unpad_fail', (out[:4].hex() if out else ''))
    if out:
        open(sys.argv[3], 'wb').write(out)
        print('wrote', sys.argv[3], len(out), hashlib.sha256(out).hexdigest())
