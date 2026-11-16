import sys, hashlib
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# usage: python3 -I 38-full.py <enc> <out.jpg>
raw = open(sys.argv[1], 'rb').read()
# OpenSSL -pass file: uses the first line of the file (up to NUL/newline) as password.
PW = bytes.fromhex('ffd8ffe1395045786966')
assert raw[:8] == b'Salted__'
salt, body = raw[8:16], raw[16:]
km = PBKDF2HMAC(algorithm=hashes.SHA256(), length=48, salt=salt, iterations=10000).derive(PW)
d = Cipher(algorithms.AES(km[:32]), modes.CBC(km[32:48])).decryptor()
p = d.update(body) + d.finalize()
u = padding.PKCS7(128).unpadder()
out = u.update(p) + u.finalize()
open(sys.argv[2], 'wb').write(out)
print('len', len(out), 'head', out[:4].hex(), 'tail', out[-2:].hex(), 'sha256', hashlib.sha256(out).hexdigest())
