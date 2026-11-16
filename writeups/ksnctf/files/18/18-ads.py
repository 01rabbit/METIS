import zipfile, struct, sys, os, hashlib
zpath, outdir = sys.argv[1], sys.argv[2]
img = zipfile.ZipFile(zpath).read('drive.img')
bps, spc = 512, 8
csz = bps * spc
rsize = 1024
mft_off = 1365 * csz
def fix(rec):
    usa_off, usa_cnt = struct.unpack_from('<HH', rec, 4)
    rec = bytearray(rec)
    for i in range(1, usa_cnt):
        pos = i * bps - 2
        rec[pos:pos+2] = rec[usa_off+2*i: usa_off+2*i+2]
    return bytes(rec)
def attrs(r):
    p = struct.unpack_from('<H', r, 0x14)[0]
    while p + 8 <= len(r):
        t, ln = struct.unpack_from('<II', r, p)
        if t == 0xFFFFFFFF or ln == 0: break
        yield p, t, ln
        p += ln
def aname(r, p):
    nl = r[p+9]; no = struct.unpack_from('<H', r, p+0x0A)[0]
    return r[p+no:p+no+2*nl].decode('utf-16le', 'replace') if nl else ''
def runlist(buf):
    out = []; p = 0; lcn = 0
    while p < len(buf) and buf[p]:
        h = buf[p]; lc = h & 15; oc = h >> 4; p += 1
        ln = int.from_bytes(buf[p:p+lc], 'little'); p += lc
        if oc == 0: out.append((None, ln))
        else:
            lcn += int.from_bytes(buf[p:p+oc], 'little', signed=True); p += oc
            out.append((lcn, ln))
    return out
for rec_no in [int(x) for x in sys.argv[3].split(',')]:
    r = fix(img[mft_off + rec_no*rsize: mft_off + (rec_no+1)*rsize])
    print('== rec', rec_no, 'flags', struct.unpack_from('<H', r, 0x16)[0])
    for p, t, ln in attrs(r):
        if t == 0x80:
            nonres = r[p+8]; nm = aname(r, p)
            if nonres == 0:
                vl = struct.unpack_from('<I', r, p+0x10)[0]; vo = struct.unpack_from('<H', r, p+0x14)[0]
                d = r[p+vo:p+vo+vl]
                print(' DATA', repr(nm), 'res', vl, 'attr_off', p, 'data_off', vo, d)
            else:
                print(' DATA', repr(nm), 'nonres')
        else:
            print(' attr', hex(t), repr(aname(r, p)), 'len', ln, 'res' if r[p+8]==0 else 'nonres')
