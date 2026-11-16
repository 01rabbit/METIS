import struct, sys
d = open(sys.argv[1], 'rb').read()
u32 = lambda o: struct.unpack_from('<I', d, o)[0]
u16 = lambda o: struct.unpack_from('<H', d, o)[0]
def uleb(o):
    r = 0; s = 0
    while True:
        b = d[o]; o += 1; r |= (b & 0x7f) << s; s += 7
        if not b & 0x80: return r, o
sids, soff = u32(56), u32(60); tids, toff = u32(64), u32(68)
pids, poff = u32(72), u32(76); fids, foff = u32(80), u32(84)
mids, moff = u32(88), u32(92); cdefs, coff = u32(96), u32(100)
def s(i):
    o = u32(soff + 4*i); l, o = uleb(o); return d[o:o+l].decode('latin1')
def t(i): return s(u32(toff + 4*i))
def m(i):
    o = moff + 8*i; c, p, n = u16(o), u16(o+2), u32(o+4)
    po = poff + 12*p
    return f"{t(c)}->{s(n)}"
def f(i):
    o = foff + 8*i; return f"{t(u16(o))}->{s(u32(o+4))}:{t(u16(o+2))}"
W = {}
for i in range(256):
    w = 1
    if i in (0x02,0x05,0x08,0x13,0x15,0x16,0x19,0x1a,0x1c,0x1f,0x20,0x22,0x23,0x29): w = 2
    if i in (0x03,0x06,0x09,0x14,0x17,0x1b,0x24,0x25,0x26,0x2a,0x2b,0x2c) or 0x6e<=i<=0x72 or 0x74<=i<=0x78: w = 3
    if i == 0x18: w = 5
    if 0x2d<=i<=0x3d or 0x44<=i<=0x6d or 0x90<=i<=0xaf or 0xd0<=i<=0xe2: w = 2
    W[i] = w
for ci in range(cdefs):
    o = coff + 32*ci
    cls = t(u32(o)); cd = u32(o+24)
    print("CLASS", cls)
    if not cd: continue
    sf, o2 = uleb(cd); inf, o2 = uleb(o2); dm, o2 = uleb(o2); vm, o2 = uleb(o2)
    for _ in range(sf+inf): _, o2 = uleb(o2); _, o2 = uleb(o2)
    mi = 0
    for _ in range(dm+vm):
        dlt, o2 = uleb(o2); mi += dlt
        af, o2 = uleb(o2); co, o2 = uleb(o2)
        print("  METHOD", m(mi))
        if not co: continue
        regs, ins, outs, tries, dbg, isz = struct.unpack_from('<HHHHII', d, co)
        print(f"   regs={regs} ins={ins}")
        p = co + 16; end = p + isz*2
        while p < end:
            w = u16(p); op = w & 0xff
            n = W[op]
            if w in (0x100,0x200,0x300):
                break
            units = [u16(p+2*k) for k in range(n)]
            ann = ''
            if op in (0x1a,): ann = repr(s(units[1]))
            elif op == 0x1b: ann = repr(s(units[1]|units[2]<<16))
            elif op in (0x1c,0x1f,0x20,0x22,0x23): ann = t(units[1])
            elif 0x6e<=op<=0x72 or 0x74<=op<=0x78: ann = m(units[1])
            elif 0x52<=op<=0x6d: ann = f(units[1])
            print(f"    {(p-co-16)//2:04x}: op{op:02x} " + ' '.join(f'{x:04x}' for x in units) + '  ' + ann)
            p += 2*n
