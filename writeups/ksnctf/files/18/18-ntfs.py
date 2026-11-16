import zipfile, struct, sys, os, hashlib
zpath, outdir = sys.argv[1], sys.argv[2]
os.makedirs(outdir, exist_ok=True)
img = zipfile.ZipFile(zpath).read('drive.img')
print('img sha256', hashlib.sha256(img).hexdigest(), len(img))
print('oem', img[3:11])
bps = struct.unpack_from('<H', img, 0x0B)[0]
spc = img[0x0D]
mft_lcn = struct.unpack_from('<Q', img, 0x30)[0]
rs = struct.unpack_from('<b', img, 0x40)[0]
csz = bps * spc
rsize = 1 << (-rs) if rs < 0 else rs * csz
print('bps', bps, 'spc', spc, 'mft_lcn', mft_lcn, 'rec', rsize, 'clus', csz)

def fix(rec):
    usa_off, usa_cnt = struct.unpack_from('<HH', rec, 4)
    rec = bytearray(rec)
    for i in range(1, usa_cnt):
        pos = i * bps - 2
        rec[pos:pos+2] = rec[usa_off+2*i: usa_off+2*i+2]
    return bytes(rec)

def runlist(buf):
    out = []; p = 0; lcn = 0
    while p < len(buf) and buf[p]:
        h = buf[p]; lc = h & 15; oc = h >> 4; p += 1
        ln = int.from_bytes(buf[p:p+lc], 'little'); p += lc
        if oc == 0:
            out.append((None, ln))
        else:
            lcn += int.from_bytes(buf[p:p+oc], 'little', signed=True); p += oc
            out.append((lcn, ln))
    return out

def attrs(r):
    p = struct.unpack_from('<H', r, 0x14)[0]
    while p + 8 <= len(r):
        t, ln = struct.unpack_from('<II', r, p)
        if t == 0xFFFFFFFF or ln == 0: break
        yield p, t, ln
        p += ln

def readdata(img, runs, real):
    data = bytearray()
    for lcn, l in runs:
        if lcn is None: data += b'\0' * (l * csz)
        else: data += img[lcn*csz:(lcn+l)*csz]
    return bytes(data[:real])

# locate MFT via record 0
r0 = fix(img[mft_lcn*csz: mft_lcn*csz+rsize])
mft_runs = []
for p, t, ln in attrs(r0):
    if t == 0x80 and r0[p+8] == 1 and r0[p+9] == 0:
        rro = struct.unpack_from('<H', r0, p+0x20)[0]
        mft_runs = runlist(r0[p+rro:p+ln])
mft = readdata(img, mft_runs, 1<<62)
print('mft runs', mft_runs, 'mft bytes', len(mft))

def fname_of(r, p):
    body = p + struct.unpack_from('<H', r, p+0x14)[0]
    parent = struct.unpack_from('<Q', r, body)[0] & 0xFFFFFFFFFFFF
    nl = r[body+0x40]; ns = r[body+0x41]
    return parent, r[body+0x42: body+0x42+2*nl].decode('utf-16le', 'replace'), ns

recs = {}
n = len(mft) // rsize
for i in range(n):
    raw = mft[i*rsize:(i+1)*rsize]
    if raw[:4] != b'FILE': continue
    r = fix(raw)
    flags = struct.unpack_from('<H', r, 0x16)[0]
    names = []; datas = []
    for p, t, ln in attrs(r):
        if t == 0x30:
            parent, nm, ns = fname_of(r, p)
            names.append((nm, parent, ns))
        if t == 0x80:
            nonres = r[p+8]
            sname = r[p+9]*2 and r[p+0x0A:p+0x0A+2*r[p+9]].decode('utf-16le','replace')
            if nonres == 0:
                vl = struct.unpack_from('<I', r, p+0x10)[0]; vo = struct.unpack_from('<H', r, p+0x14)[0]
                datas.append((sname, 'res', r[p+vo:p+vo+vl]))
            else:
                real = struct.unpack_from('<Q', r, p+0x30)[0]
                rro = struct.unpack_from('<H', r, p+0x20)[0]
                datas.append((sname, 'nonres', (runlist(r[p+rro:p+ln]), real)))
    recs[i] = (flags, names, datas)

for i, (flags, names, datas) in recs.items():
    nm = names[0][0] if names else '?'
    print('rec', i, 'inuse' if flags & 1 else 'deleted', 'dir' if flags & 2 else 'file', nm, [(n_[0], n_[1]) for n_ in names][:2])
    for sname, kind, d in datas:
        if kind == 'res':
            print('   stream', repr(sname), 'resident', len(d), d[:120])
        else:
            print('   stream', repr(sname), 'nonres runs', d[0][:4], 'real', d[1])
        if kind == 'nonres' or True:
            pass
    for sname, kind, d in datas:
        if kind == 'res':
            fn = f'rec{i}_{nm}_{sname or "data"}.bin'
            safe = ''.join(c if c.isalnum() or c in '._-' else '_' for c in fn)
            open(os.path.join(outdir, safe), 'wb').write(d)
        else:
            try:
                blob = readdata(img, d[0], d[1])
                fn = f'rec{i}_{nm}_{sname or "data"}.bin'
                safe = ''.join(c if c.isalnum() or c in '._-' else '_' for c in fn)
                open(os.path.join(outdir, safe), 'wb').write(blob)
            except Exception as e:
                print('   err', e)
