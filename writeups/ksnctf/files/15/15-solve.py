import hashlib, sys
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
APK = "/Users/makoto.sugita/personal/METIS/.metis-state/.metis-artifacts-5u_i_eoe/.metis-web/dd5fcd3c4be24638ba244b285b21b2cd.apk"
import zipfile
ct = zipfile.ZipFile(APK).read("res/raw/jewel_c.png")
TARGET = "356280a58d3c437a45268a0b226d8cccad7b5dd28f5d1b37abf1873cc426a8a5"
def h(s):
    b = hashlib.sha256(s.encode()).digest()
    return format(int.from_bytes(b, 'big', signed=True), 'x')
def luhn(s14):
    t = 0
    for i, c in enumerate(reversed(s14)):
        v = int(c)
        if i % 2 == 0:
            v *= 2; v = v - 9 if v > 9 else v
        t += v
    return str((10 - t % 10) % 10)
found = None
for n in range(10**6):          # 15 digits: 8 prefix + 6 free + Luhn check digit
    s14 = "99999991%06d" % n
    imei = s14 + luhn(s14)
    if h(imei) == TARGET: found = imei; break
if not found:
    for n in range(10**7):      # fallback: no Luhn assumption
        imei = "99999991%07d" % n
        if h(imei) == TARGET: found = imei; break
print("imei found:", bool(found))
key = ("!" + found).encode()
pt = Cipher(algorithms.AES(key), modes.CBC(b"kLwC29iMc4nRMuE5")).decryptor()
out = pt.update(ct) + pt.finalize()
out = out[:-out[-1]]
open("/Users/makoto.sugita/personal/METIS/.metis-state/work/15-jewel.png", "wb").write(out)
print(out[:8], len(out))
