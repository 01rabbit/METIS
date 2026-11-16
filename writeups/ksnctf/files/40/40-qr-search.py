#!/usr/bin/env python3
"""Structured search: QR v2 (25x25, 1px/module, light=1) inside 32x32; fix function patterns,
greedy bit-flip ascent on log p(flag) of the affine model, then decode. Usage: python3 -I 40-qr-search.py Q40DIR ARTDIR"""
import sys, random, math
SRC = open("/Users/makoto.sugita/personal/METIS/.metis-state/work/40-deep-flag-recover.py").read().rsplit("\nmain()", 1)[0]
g = {"__name__": "lib"}
exec(compile(SRC, "lib", "exec"), g)
raw = open(g["DATA"], "rb").read()
import struct
vals = struct.unpack_from("<%df" % (len(raw) // 4), raw, 0)
W, _ = g["parse_layout"](vals, 0, False, False, False)
bn = {k: g["bn_ab"](W, k) for k in range(1, 14, 2)}
A = g["jacobian_rows"](W, bn)
_, c = g["forward"]([0.0] * 1024, W, bn)
N = 25
def func_mask():
    f = {}
    def fin(r0, c0):
        for i in range(-1, 8):
            for j in range(-1, 8):
                r, cc = r0 + i, c0 + j
                if 0 <= r < N and 0 <= cc < N:
                    d = max(abs(i - 3), abs(j - 3))
                    f[(r, cc)] = 1 if d in (3,) or d <= 1 else 0  # 1=dark
                    if i in (-1, 7) or j in (-1, 7): f[(r, cc)] = 0
    fin(0, 0); fin(0, N - 7); fin(N - 7, 0)
    for i in range(8, N - 8):
        f[(6, i)] = f[(i, 6)] = 1 if i % 2 == 0 else 0
    for i in range(-2, 3):
        for j in range(-2, 3):
            f[(18 + i, 18 + j)] = 1 if max(abs(i), abs(j)) != 1 else 0
    f[(N - 8, 8)] = 1
    return f
F = func_mask()
for i in range(9):  # format areas: free-ish but keep as free
    pass
def lse_logp(z):
    m = max(z); return z[10] - m - math.log(sum(math.exp(v - m) for v in z))
def run(ox, oy, seed):
    rnd = random.Random(seed)
    x = [1.0] * 1024
    free = []
    for r in range(N):
        for cc in range(N):
            p = (oy + r) * 32 + ox + cc
            if (r, cc) in F: x[p] = 0.0 if F[(r, cc)] else 1.0
            else:
                free.append(p); x[p] = float(rnd.random() < 0.5)
    z = [c[j] + sum(A[j][i] for i in range(1024) if x[i]) for j in range(11)]
    best = lse_logp(z)
    imp = True
    while imp:
        imp = False
        rnd.shuffle(free)
        for p in free:
            d = 1.0 - 2.0 * x[p]
            z2 = [z[j] + d * A[j][p] for j in range(11)]
            v = lse_logp(z2)
            if v > best + 1e-9:
                best, z, x[p] = v, z2, 1.0 - x[p]; imp = True
    return best, x
res = []
for ox in range(0, 8):
    for oy in range(0, 8):
        b, x = run(ox, oy, 1)
        res.append((b, ox, oy, x))
res.sort(key=lambda t: -t[0])
for b, ox, oy, x in res[:6]:
    print("off", ox, oy, "p(flag)=%.4f" % math.exp(b))
b, ox, oy, x = res[0]
for seed in range(2, 6):
    bb, xx = run(ox, oy, seed)
    print("seed", seed, "p=%.4f" % math.exp(bb))
    if bb > b: b, x = bb, xx
M = [[1 - int(x[(oy + r) * 32 + ox + cc]) for cc in range(N)] for r in range(N)]  # 1=dark
for row in M: print("".join("#" if v else "." for v in row))
import json
json.dump({"off": [ox, oy], "M": M}, open("/Users/makoto.sugita/personal/METIS/.metis-state/work/40-qr-grid.json", "w"))
