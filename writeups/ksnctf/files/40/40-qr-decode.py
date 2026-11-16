#!/usr/bin/env python3
"""Decode v2 QR grid from 40-qr-grid.json (byte mode)."""
import json
M = json.load(open("/Users/makoto.sugita/personal/METIS/.metis-state/work/40-qr-grid.json"))["M"]
N = 25
def fmt_code(d):
    v = d << 10; g = 0b10100110111
    for k in range(14, 9, -1):
        if (v >> k) & 1: v ^= g << (k - 10)
    return ((d << 10) | v) ^ 0x5412
P1 = [(i, 8) if i < 6 else (7, 8) if i == 6 else (8, 8) if i == 7 else (8, 7) if i == 8 else (8, 14 - i) for i in range(15)]
P2 = [(8, N - 1 - i) if i < 8 else (N - 15 + i, 8) for i in range(15)]
v1 = sum(M[r][c] << i for i, (r, c) in enumerate(P1)); v2 = sum(M[r][c] << i for i, (r, c) in enumerate(P2))
for d in range(32):
    a, b = bin(v1 ^ fmt_code(d)).count("1"), bin(v2 ^ fmt_code(d)).count("1")
    if a + b <= 6: print("format", d, "ec", d >> 3, "mask", d & 7, "dist", a, b)
def mb(m, i, j):
    return [(i+j)%2==0, i%2==0, j%3==0, (i+j)%3==0, (i//2+j//3)%2==0, (i*j)%2+(i*j)%3==0, ((i*j)%2+(i*j)%3)%2==0, ((i+j)%2+(i*j)%3)%2==0][m]
func = [[False]*N for _ in range(N)]
for r in range(N):
    for c in range(N):
        if (r<9 and c<9) or (r<9 and c>=N-8) or (r>=N-8 and c<9) or r==6 or c==6 or (16<=r<=20 and 16<=c<=20): func[r][c] = True
for mask in range(8):
    bits = []; col = N-1; up = True
    while col > 0:
        if col == 6: col -= 1
        for r in (range(N-1,-1,-1) if up else range(N)):
            for cc in (col, col-1):
                if not func[r][cc]: bits.append(M[r][cc] ^ (1 if mb(mask, r, cc) else 0))
        up = not up; col -= 2
    by = [int("".join(map(str, bits[k:k+8])), 2) for k in range(0, len(bits)-7, 8)]
    print(mask, bits[:4], bytes(by[:20]))
    if bits[:4] == [0,1,0,0] and mask == 7:
        ln = by[0]<<4 | by[1]>>4 if False else int("".join(map(str,bits[4:12])),2)
        print("MASK", mask, "len", ln, bytes(int("".join(map(str,bits[12+8*k:20+8*k])),2) for k in range(ln)))

# RS syndrome check (v2-Q: 1 block, 22 data + 22 ec)
exp = [0]*512; log = [0]*256; x = 1
for i in range(255):
    exp[i] = x; log[x] = i; x <<= 1
    if x & 256: x ^= 0x11d
for i in range(255, 512): exp[i] = exp[i-255]
def mul(a, b): return 0 if a == 0 or b == 0 else exp[log[a]+log[b]]
cw = by[:44]
syn = []
for k in range(22):
    s = 0
    for v in cw: s = mul(s, exp[k]) ^ v
    syn.append(s)
print("RS syndromes all zero:", all(s == 0 for s in syn))

def inv(a): return exp[255-log[a]]
def pmul(p, q):
    r = [0]*(len(p)+len(q)-1)
    for i, a in enumerate(p):
        for j, b in enumerate(q): r[i+j] ^= mul(a, b)
    return r
# Berlekamp-Massey (lowest-degree first locator)
C=[1]; B=[1]; L=0; m=1; b=1
for n in range(22):
    d = syn[n]
    for i in range(1, L+1):
        if i < len(C): d ^= mul(C[i], syn[n-i])
    if d == 0: m += 1; continue
    T = C[:]
    coef = mul(d, inv(b))
    C = C + [0]*(len(B)+m-len(C))
    for i, v in enumerate(B): C[i+m] ^= mul(coef, v)
    if 2*L <= n: L = n+1-L; B = T; b = d; m = 1
    else: m += 1
print("errors located:", L)
n = 44
pos = [i for i in range(n) if sum(mul(c, exp[(i_pw*i) % 255]) for c, i_pw in [(C[j], j) for j in range(len(C))] ) == 0 and False]
# Chien: position p (index from start) has locator X = alpha^(n-1-p); roots at X^-1
locs = []
for p in range(n):
    Xi = exp[(255-(n-1-p)) % 255]
    v = 0
    for j, cj in enumerate(C): v ^= mul(cj, exp[(log[Xi]*j) % 255]) if cj and Xi else (cj if j == 0 else 0)
    if v == 0: locs.append(p)
print("error positions:", locs)
# Forney via solving linear system by brute: error magnitudes with syndromes
# S_k = sum e_p * alpha^{k*(n-1-p)}
import itertools
def solve(locs):
    t = len(locs)
    Mx = [[exp[(k*(n-1-p)) % 255] for p in locs] + [syn[k]] for k in range(t)]
    for i in range(t):
        pv = next(r for r in range(i, t) if Mx[r][i]); Mx[i], Mx[pv] = Mx[pv], Mx[i]
        iv = inv(Mx[i][i]); Mx[i] = [mul(v, iv) for v in Mx[i]]
        for r in range(t):
            if r != i and Mx[r][i]:
                f = Mx[r][i]; Mx[r] = [a ^ mul(f, bb) for a, bb in zip(Mx[r], Mx[i])]
    return [Mx[i][t] for i in range(t)]
if len(locs) == L and L:
    mags = solve(locs)
    fixed = cw[:]
    for p, e in zip(locs, mags): fixed[p] ^= e
    s2 = []
    for k in range(22):
        s = 0
        for v in fixed: s = mul(s, exp[k]) ^ v
        s2.append(s)
    print("after fix zero:", all(s == 0 for s in s2))
    ln = (fixed[0] & 15) << 4 | fixed[1] >> 4
    print("FIXED", ln, bytes(((fixed[1+k] & 15) << 4) | (fixed[2+k] >> 4) for k in range(ln)))
