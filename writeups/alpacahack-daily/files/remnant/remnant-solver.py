#!/usr/bin/env python3
"""remnant solver (AlpacaHack Daily, Misc).

Oracle (service): reads one line x, computes b64decode(XOR(flag, x)) over
zip-truncated bytes and answers "Error..." if that raises, else "Incorrect..."
(or "Correct!" when x == flag). flag = b64encode(inner).

Protocol of this script: writes one query line per request to stdout
(service input) and reads exactly one response line per request from stdin
(service output). The recovered inner flag is printed to stderr.

Idea: b64decode(validate=False) silently drops non-alphabet bytes. If the
counted (alphabet) characters before position i are a fixed known pattern
(filler bytes that are dropped), then the only counted byte in the query is
r_i = flag_i ^ t, and the result is Error iff r_i is in the base64 alphabet.
That is a 1-bit membership test per query, which an adaptive split narrows
over the 65 possible flag characters (64 alphabet chars plus '=').
Reaching position i where the flag has ended is detected by the query
being truncated to the flag length, which always answers "valid", so the
verification step returns "Incorrect..." instead of the predicted "Error...".
"""
import base64
import sys

ALPHA = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")
CAND = ALPHA | {ord("=")}          # possible flag bytes
TEST_BYTES = range(0x21, 0x7F)     # printable query bytes (no space, no newline)


def _pad_for(v):
    """Filler r: not alphabet, not '=', and x = v ^ r printable and non-zero."""
    for r in range(1, 256):
        if r in CAND:
            continue
        x = v ^ r
        if 0x21 <= x <= 0x7E:
            return r
    raise ValueError("no filler for %d" % v)


PAD = {v: _pad_for(v) for v in CAND}


def prefix_bytes(known):
    # Query bytes that make every known position decode to an ignored byte.
    return bytes(v ^ PAD[v] for v in known)


def recover_byte(ask, known):
    """Return the flag byte at len(known), or None if the flag has ended."""
    base = prefix_bytes(known)
    cands = set(CAND)
    while True:
        if not cands:
            return None
        if len(cands) == 1:
            v = next(iter(cands))
            t = next(t for t in TEST_BYTES if (v ^ t) in ALPHA)
            # predicted "Error..." if v is right; "Incorrect..." if flag ended
            return v if ask(base + bytes([t])) == "E" else None
        best_t, best_score = None, -1
        for t in TEST_BYTES:
            s = sum(1 for v in cands if (v ^ t) not in ALPHA)
            score = min(s, len(cands) - s)
            if score > best_score:
                best_t, best_score = t, score
        if best_score <= 0:
            raise RuntimeError("candidates not separable: %r" % sorted(cands))
        t = best_t
        r = ask(base + bytes([t]))
        if r == "C":
            raise RuntimeError("unexpected Correct! mid-search")
        if r == "E":
            cands = {v for v in cands if (v ^ t) in ALPHA}
        else:
            cands = {v for v in cands if (v ^ t) not in ALPHA}


def solve(ask, log=None):
    known = []
    while True:
        v = recover_byte(ask, known)
        if v is None:
            break
        known.append(v)
        if log:
            log("pos %d -> %r" % (len(known) - 1, chr(v)))
        if len(known) > 4096:
            raise RuntimeError("runaway")
    return bytes(known)


def make_pipe_ask(inp, out, counter):
    def ask(data):
        out.write(data.decode("ascii") + "\n")
        out.flush()
        counter[0] += 1
        line = inp.readline()
        if not line:
            raise EOFError("service closed")
        if "Correct!" in line:
            return "C"
        if "Incorrect" in line:
            return "I"
        if "Error" in line:
            return "E"
        raise RuntimeError("unexpected response: %r" % line)
    return ask


def main():
    counter = [0]
    ask = make_pipe_ask(sys.stdin, sys.stdout, counter)
    log = lambda m: print(m, file=sys.stderr, flush=True)
    s = solve(ask, log=log)
    log("base64 flag: %d chars, queries so far %d" % (len(s), counter[0]))
    try:
        inner = base64.b64decode(s)
        log("INNER FLAG: " + inner.decode("ascii", errors="replace"))
    except Exception as e:  # pragma: no cover
        log("decode failed: %r" % e)
    r = ask(s)
    log("final confirm response: %s (total queries %d)" % (r, counter[0]))


if __name__ == "__main__":
    main()
