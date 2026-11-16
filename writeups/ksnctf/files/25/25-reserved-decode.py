#!/usr/bin/env python3
"""Static decoder for the ksnctf #25 "Reserved" word sequence.

Never executes the challenge program. It lexes the word stream the way Perl
would (q/qq/qw/m/s/tr/y with a whitespace-separated delimiter), then evaluates
each `print chr F1 F2 ... Q` statement by applying the function chain from the
inside out. Prints the reconstructed output string.
"""
import html
import re
import sys

PAGE = '/Users/makoto.sugita/personal/METIS/.metis-state/.metis-artifacts-nzdzouck/00-problem.html'
QOPS = {'q', 'qq', 'qw', 'm', 's', 'tr', 'y', 'qr', 'qx'}
PAIRS = {'(': ')', '[': ']', '{': '}', '<': '>'}


def read_delim(text, p, open_ch):
    close_ch = PAIRS.get(open_ch, open_ch)
    depth, buf, q, n = 1, [], p, len(text)
    while q < n:
        c = text[q]
        if c == '\\' and q + 1 < n:
            buf.append(text[q:q + 2])
            q += 2
            continue
        if open_ch != close_ch and c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return ''.join(buf), q + 1
        buf.append(c)
        q += 1
    raise ValueError('unterminated quote at %d' % p)


def lex(text):
    toks, pos, n = [], 0, len(text)

    def skip_ws(p):
        while p < n and text[p].isspace():
            p += 1
        return p

    while True:
        pos = skip_ws(pos)
        if pos >= n:
            break
        m = re.match(r'[A-Za-z_]\w*', text[pos:])
        if not m:
            toks.append(('P', text[pos]))
            pos += 1
            continue
        w = m.group(0)
        pos += len(w)
        if w in QOPS and pos < n and text[pos].isspace():
            p2 = skip_ws(pos)
            d = text[p2]
            body, p3 = read_delim(text, p2 + 1, d)
            if w in ('s', 'tr', 'y'):
                # second part is not needed for this sample; keep the raw body
                toks.append(('QS', w, d, body))
                pos = p3
                pos += len(re.match(r'[a-z]*', text[pos:]).group(0))
            else:
                toks.append(('Q', w, d, body))
                pos = p3
        else:
            toks.append(('W', w))
    return toks


def perl_oct(s):
    s = s.strip()
    if s[:2] in ('0x', '0X'):
        return int(re.match(r'[0-9a-fA-F_]*', s[2:]).group(0).replace('_', '') or '0', 16)
    if s[:2] in ('0b', '0B'):
        return int(re.match(r'[01_]*', s[2:]).group(0).replace('_', '') or '0', 2)
    if s[:2] in ('0o', '0O'):
        s = s[2:]
    return int(re.match(r'[0-7_]*', s).group(0).replace('_', '') or '0', 8)


def perl_hex(s):
    s = s.strip()
    if s[:2] in ('0x', '0X'):
        s = s[2:]
    return int(re.match(r'[0-9a-fA-F_]*', s).group(0).replace('_', '') or '0', 16)


def scalar(v):
    return v[-1] if isinstance(v, list) and v else v


def apply_fn(fn, v):
    v = scalar(v)
    if fn == 'chr':
        return chr(int(v))
    if fn == 'ord':
        return ord(str(v)[0]) if str(v) else 0
    if fn == 'uc':
        return str(v).upper()
    if fn == 'lc':
        return str(v).lower()
    if fn == 'length':
        return len(str(v))
    if fn == 'oct':
        return perl_oct(str(v))
    if fn == 'hex':
        return perl_hex(str(v))
    raise ValueError('unsupported function: ' + fn)


def quote_value(tok):
    return tok[3].split() if tok[1] == 'qw' else tok[3]


def decode(toks):
    out = []
    i = 0
    while i < len(toks):
        if toks[i] == ('W', 'print'):
            if toks[i + 1] != ('W', 'chr'):
                raise ValueError('expected chr after print')
            j, funcs = i + 2, []
            while toks[j][0] == 'W':
                funcs.append(toks[j][1])
                j += 1
            if toks[j][0] != 'Q':
                raise ValueError('expected quote term at token %d' % j)
            v = quote_value(toks[j])
            for fn in reversed(funcs):
                v = apply_fn(fn, v)
            out.append(chr(v) if isinstance(v, int) else v)
            i = j + 1
        else:
            i += 1
    return ''.join(out)


def main():
    src = open(PAGE, encoding='utf-8').read()
    code = html.unescape(re.search(r'<code>(.*?)</code>', src, re.S).group(1))
    result = decode(lex(code))
    print(repr(result))
    m = re.match(r'FLAG_\w+', result)
    if m:
        print('FLAG:', m.group(0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
