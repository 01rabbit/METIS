import zipfile, sys, os, re, hashlib
zpath, outdir, html = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(outdir, exist_ok=True)
img = zipfile.ZipFile(zpath).read('drive.img')
for pat in [rb'ksnctf', rb'FLAG', rb'flag', rb'\{[^}\x00]{0,80}\}']:
    hits = [m.start() for m in re.finditer(pat, img)]
    print('pattern', pat, 'hits', len(hits), hits[:10])
for m in re.finditer(rb'[A-Za-z0-9_+/=]{2,}', img):
    pass
# jpeg tails: data after FFD9 for each jpeg start found
for name, off, size in [('carl', 130*4096, 80972), ('liberty', 150*4096, 173276), ('mona', 193*4096, 48058), ('wave', 205*4096, 135599)]:
    d = img[off:off+size]
    e = d.rfind(b'\xff\xd9')
    print(name, 'head', d[:4].hex(), 'eoi at', e, 'len', len(d), 'tail after eoi', len(d)-e-2 if e>=0 else None)
    if e >= 0 and len(d)-e-2 > 0:
        print('  trailer head', d[e+2:e+2+64])
    open(os.path.join(outdir, name + '.jpg'), 'wb').write(d)
    print('  sha256', hashlib.sha256(d).hexdigest())
t = open(html, 'rb').read().decode('utf-8', 'replace')
for m in re.finditer(r'(?i)flag[^<]{0,120}', t):
    print('html:', m.group(0)[:140])
