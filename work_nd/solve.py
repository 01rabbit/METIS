import re, io, json, tarfile
from math import isqrt

def long_to_bytes(x):
    return x.to_bytes((x.bit_length() + 7) // 8, 'big')


d = json.load(open('work_nd/out.json'))['result']
t = tarfile.open(fileobj=io.BytesIO(bytes.fromhex(d['hex'])))
txt = t.extractfile('neighborhood-distance/output.txt').read().decode()
v = {k: int(x) for k, x in re.findall(r'(\w+)\s*=\s*(\d+)', txt)}
e = v['e']
n = [v['n1'], v['n2'], v['n3']]
c = [v['c1'], v['c2'], v['c3']]
W = 1 << 19


def find(a, b, cc):
    # a=p*qq, b=q*rr, cc=r*pp -> p ~ sqrt(a*cc/b)
    est = isqrt(a * cc // b)
    for x in range(est - W, est + W):
        if x > 1 and a % x == 0:
            return x
    return None


p = find(n[0], n[1], n[2])
q = find(n[1], n[2], n[0])
r = find(n[2], n[0], n[1])
print(p is not None, q is not None, r is not None)
out = b''
for N, C, f in ((n[0], c[0], p), (n[1], c[1], q), (n[2], c[2], r)):
    g = N // f
    phi = (f - 1) * (g - 1)
    m = pow(C, pow(e, -1, phi), N)
    out += long_to_bytes(m)
print(out)
