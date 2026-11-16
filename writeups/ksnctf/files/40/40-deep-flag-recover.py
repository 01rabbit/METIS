#!/usr/bin/env python3
"""Recover the 'flag' input of the Deep Flag Network model (pure python, no TF/numpy).

Facts used:
- The model has no activation functions (Dense without activation, BN in
  inference mode, Softmax at the end), so logits z = A x + c is affine in the
  1024 input pixels (32x32 grayscale, 0..1).
- The truncated SavedModel variables blob (index file missing) holds the float
  weights contiguously. The tensor order is unknown, so layouts are searched and
  accepted only if they reproduce the published probabilities for no_flag_0.png.
- Then projected gradient ascent on log p(flag) over [0,1]^1024, binarize, and
  try a minimal QR (byte mode) reader.

Usage: python3 -I 40-deep-flag-recover.py SCRATCH_Q40_DIR ARTIFACT_DIR
"""
import itertools
import math
import struct
import sys
import zlib

SCR, ART = sys.argv[1], sys.argv[2]
DATA = SCR + "/model/variables/variables.data-00000-of-00001"
NAMES = ["airplane", "automobile", "bird", "cat", "deer", "dog", "frog", "horse", "ship", "truck", "flag"]
PUBLISHED_NO_FLAG = [3.37, 19.07, 6.17, 11.03, 9.29, 9.65, 17.56, 6.71, 5.42, 9.89, 1.84]
DENSE = {0: (1024, 512), 2: (512, 256), 4: (256, 128), 6: (128, 64), 8: (64, 32), 10: (32, 16), 12: (16, 11)}


def read_png_gray(path):
    d = open(path, "rb").read()
    assert d[:8] == b"\x89PNG\r\n\x1a\n"
    p, idat, w, h = 8, b"", 0, 0
    while p < len(d):
        (ln,) = struct.unpack(">I", d[p:p + 4])
        typ = d[p + 4:p + 8]
        body = d[p + 8:p + 8 + ln]
        if typ == b"IHDR":
            w, h, bd, ct = struct.unpack(">IIBB", body[:10])
            assert bd == 8 and ct == 0
        elif typ == b"IDAT":
            idat += body
        p += 12 + ln
    raw = zlib.decompress(idat)
    prev = [0] * w
    rows, q = [], 0
    for _ in range(h):
        f = raw[q]
        q += 1
        line = raw[q:q + w]
        q += w
        out = [0] * w
        for x in range(w):
            a = out[x - 1] if x > 0 else 0
            b = prev[x]
            c = prev[x - 1] if x > 0 else 0
            v = line[x]
            if f == 0:
                r = v
            elif f == 1:
                r = v + a
            elif f == 2:
                r = v + b
            elif f == 3:
                r = v + ((a + b) >> 1)
            else:
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                r = v + pr
            out[x] = r & 255
        rows.append(out)
        prev = out
    return rows


def parse_layout(vals, S, sorted_order, bias_first, beta_first):
    """Sequentially read weights starting at float index S under a candidate layout."""
    W, p = {}, S
    order = sorted(range(14), key=str) if sorted_order else list(range(14))
    for idx in order:
        if idx % 2 == 0:
            fi, fo = DENSE[idx]
            parts = [("b", fo), ("k", fi * fo)] if bias_first else [("k", fi * fo), ("b", fo)]
            for nm, cnt in parts:
                W[nm + str(idx)] = list(vals[p:p + cnt])
                p += cnt
        else:
            w = DENSE[idx - 1][1]
            names = ["beta", "gamma", "mm", "mv"] if beta_first else ["gamma", "beta", "mm", "mv"]
            for nm in names:
                W[nm + str(idx)] = list(vals[p:p + w])
                p += w
    return W, p


def bn_ab(W, idx, eps=1e-3):
    w = len(W["beta%d" % idx])
    a = [W["gamma%d" % idx][i] / math.sqrt(max(W["mv%d" % idx][i] + eps, 1e-12)) for i in range(w)]
    s = [W["beta%d" % idx][i] - W["mm%d" % idx][i] * a[i] for i in range(w)]
    return a, s


def forward(x, W, bn):
    h = list(x)
    for k in range(0, 14, 2):
        fi, fo = DENSE[k]
        K = W["k%d" % k]
        y = list(W["b%d" % k])
        for i in range(fi):
            xi = h[i]
            if xi:
                row = K[i * fo:(i + 1) * fo]
                y = [yo + xi * ko for yo, ko in zip(y, row)]
        a, s = bn[k + 1]
        h = [a[o] * y[o] + s[o] for o in range(fo)]
    m = max(h)
    e = [math.exp(v - m) for v in h]
    t = sum(e)
    return [v / t for v in e], h


def jacobian_rows(W, bn):
    rows = []
    for j in range(11):
        g = [0.0] * 11
        g[j] = 1.0
        for k in range(12, -1, -2):
            a, _ = bn[k + 1]
            g = [g[o] * a[o] for o in range(len(g))]
            fi, fo = DENSE[k]
            K = W["k%d" % k]
            g = [sum(kv * gv for kv, gv in zip(K[i * fo:(i + 1) * fo], g)) for i in range(fi)]
        rows.append(g)
    return rows


# ---------- minimal QR reader (byte mode, no RS correction) ----------
def fmt_code(d):
    v = d << 10
    g = 0b10100110111
    for k in range(14, 9, -1):
        if (v >> k) & 1:
            v ^= g << (k - 10)
    return ((d << 10) | v) ^ 0x5412


def mask_bit(m, i, j):
    if m == 0:
        return (i + j) % 2 == 0
    if m == 1:
        return i % 2 == 0
    if m == 2:
        return j % 3 == 0
    if m == 3:
        return (i + j) % 3 == 0
    if m == 4:
        return (i // 2 + j // 3) % 2 == 0
    if m == 5:
        return (i * j) % 2 + (i * j) % 3 == 0
    if m == 6:
        return ((i * j) % 2 + (i * j) % 3) % 2 == 0
    return ((i + j) % 2 + (i * j) % 3) % 2 == 0


ALIGN = {2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34]}


def qr_candidates(G):
    S = len(G)
    dark = [(r, c) for r in range(S) for c in range(S) if G[r][c]]
    if not dark:
        return "empty", None, []
    r0, c0 = min(dark)  # first dark pixel in row-major order = top-left finder corner
    run = 0
    while c0 + run < S and G[r0][c0 + run]:
        run += 1
    cmax = max(c for _, c in dark)
    npx = cmax - c0 + 1
    est = run / 7.0
    _, N, mf = min((abs(npx / n - est), n, npx / n) for n in range(21, 46, 4))
    M = []
    for i in range(N):
        row = []
        for j in range(N):
            r = int(r0 + (i + 0.5) * mf)
            c = int(c0 + (j + 0.5) * mf)
            row.append(G[r][c] if (0 <= r < S and 0 <= c < S) else 0)
        M.append(row)
    info = {"run": run, "N": N, "module_px": round(mf, 3), "origin": (r0, c0)}

    P1, P2 = [], []
    for i in range(15):
        P1.append((i, 8) if i < 6 else (7, 8) if i == 6 else (8, 8) if i == 7 else (8, 7) if i == 8 else (8, 14 - i))
        P2.append((8, N - 1 - i) if i < 8 else (N - 15 + i, 8))
    v1 = sum(M[r][c] << i for i, (r, c) in enumerate(P1))
    v2 = sum(M[r][c] << i for i, (r, c) in enumerate(P2))
    best_d = min(range(32), key=lambda d: bin(v1 ^ fmt_code(d)).count("1") + bin(v2 ^ fmt_code(d)).count("1"))
    info["format_mask"] = best_d & 7
    info["format_dist"] = bin(v1 ^ fmt_code(best_d)).count("1") + bin(v2 ^ fmt_code(best_d)).count("1")

    version = (N - 17) // 4
    func = [[False] * N for _ in range(N)]
    for r in range(N):
        for c in range(N):
            if (r < 9 and c < 9) or (r < 9 and c >= N - 8) or (r >= N - 8 and c < 9):
                func[r][c] = True
            elif r == 6 or c == 6:
                func[r][c] = True
    if version in ALIGN:
        last = ALIGN[version][-1]
        for a in ALIGN[version]:
            for b in ALIGN[version]:
                if (a, b) in ((6, 6), (6, last), (last, 6)):
                    continue
                for r in range(a - 2, a + 3):
                    for c in range(b - 2, b + 3):
                        func[r][c] = True

    results = []
    for pol in (0, 1):
        for mask in range(8):
            bits = []
            col, up = N - 1, True
            while col > 0:
                if col == 6:
                    col -= 1
                for r in (range(N - 1, -1, -1) if up else range(N)):
                    for cc in (col, col - 1):
                        if not func[r][cc]:
                            b = M[r][cc] ^ pol
                            if mask_bit(mask, r, cc):
                                b ^= 1
                            bits.append(b)
                up = not up
                col -= 2
            if len(bits) < 12 or bits[0:4] != [0, 1, 0, 0]:
                continue
            ln = int("".join(map(str, bits[4:12])), 2)
            body = bits[12:12 + 8 * ln]
            if ln == 0 or len(body) < 8 * ln:
                continue
            data = bytes(int("".join(map(str, body[k:k + 8])), 2) for k in range(0, 8 * ln, 8))
            if all(32 <= x < 127 for x in data):
                results.append((pol, mask, ln, data.decode("ascii")))
    return info, M, results


def main():
    raw = open(DATA, "rb").read()
    vals = struct.unpack_from("<%df" % (len(raw) // 4), raw, 0)
    img = read_png_gray(ART + "/04-03-no_flag_0.png")
    x0 = [img[r][c] / 255.0 for r in range(32) for c in range(32)]

    chosen = None
    for sorted_order, bias_first, beta_first in itertools.product((True, False), repeat=3):
        Wt, _ = parse_layout(vals, 0, sorted_order, bias_first, beta_first)
        bnt = {k: bn_ab(Wt, k) for k in range(1, 14, 2)}
        probs, _ = forward(x0, Wt, bnt)
        diff = max(abs(p * 100 - e) for p, e in zip(probs, PUBLISHED_NO_FLAG))
        tag = (sorted_order, bias_first, beta_first)
        print("layout sorted=%s bias_first=%s beta_first=%s max_diff=%.3f" % (tag + (diff,)))
        if diff < 0.05 and chosen is None:
            chosen = (Wt, bnt, tag)
    if chosen is None:
        print("VERIFICATION FAILED: no tested layout reproduces published output")
        return
    W, bn, tag = chosen
    print("verified layout", tag, "; probs:", [(NAMES[i], round(forward(x0, W, bn)[0][i] * 100, 2)) for i in range(11)])

    A = jacobian_rows(W, bn)
    _, c = forward([0.0] * 1024, W, bn)
    _, zf = forward(x0, W, bn)
    zlin = [sum(a * b for a, b in zip(A[j], x0)) + c[j] for j in range(11)]
    print("affine check (max |z_lin - z_fwd|):", max(abs(zlin[j] - zf[j]) for j in range(11)))

    x = [0.5] * 1024
    for it in range(400):
        z = [sum(a * b for a, b in zip(A[j], x)) + c[j] for j in range(11)]
        m = max(z)
        e = [math.exp(v - m) for v in z]
        t = sum(e)
        p = [v / t for v in e]
        delta = [-pj for pj in p]
        delta[10] += 1.0
        grad = [sum(delta[j] * A[j][i] for j in range(11)) for i in range(1024)]
        gmax = max(abs(g) for g in grad) or 1.0
        step = 0.1 if it < 100 else 0.02
        x = [min(1.0, max(0.0, xi + step * gi / gmax)) for xi, gi in zip(x, grad)]
    B = [[1 if x[r * 32 + c] > 0.5 else 0 for c in range(32)] for r in range(32)]
    xb = [float(v) for row in B for v in row]
    pb, _ = forward(xb, W, bn)
    print("binarized image: p(flag) =", round(pb[10] * 100, 2), "% ; argmax =", NAMES[pb.index(max(pb))])
    print("ASCII (#=1):")
    for row in B:
        print("".join("#" if v else "." for v in row))
    info, M, results = qr_candidates(B)
    print("QR info:", info)
    inv = [[1 - v for v in row] for row in B]
    info2, _, results2 = qr_candidates(inv)
    print("QR info (inverted):", info2)
    for res in results + results2:
        print("decoded candidate (pol, mask, len, text):", res)


main()
