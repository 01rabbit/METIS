import zipfile, zlib, struct, sys
SRC='/Users/makoto.sugita/personal/METIS/.metis-state/.metis-artifacts-ib1r3ybr/01-00-secret.zip'
OUT=sys.argv[1]
def png_decode(b):
    assert b[:8]==b'\x89PNG\r\n\x1a\n'
    p=8; idat=b''
    while p<len(b):
        n,=struct.unpack('>I',b[p:p+4]); t=b[p+4:p+8]; d=b[p+8:p+8+n]; p+=12+n
        if t==b'IHDR': w,h,bd,ct=struct.unpack('>IIBB',d[:10])
        elif t==b'IDAT': idat+=d
    bpp={6:4,2:3,0:1}[ct]; raw=zlib.decompress(idat); st=w*bpp; rows=[]; prev=bytearray(st); q=0
    for _ in range(h):
        f=raw[q]; line=bytearray(raw[q+1:q+1+st]); q+=1+st
        for i in range(st):
            a=line[i-bpp] if i>=bpp else 0; u=prev[i]; c=prev[i-bpp] if i>=bpp else 0
            if f==1: line[i]=(line[i]+a)&255
            elif f==2: line[i]=(line[i]+u)&255
            elif f==3: line[i]=(line[i]+(a+u)//2)&255
            elif f==4:
                pp=a+u-c; pa,pb,pc=abs(pp-a),abs(pp-u),abs(pp-c)
                line[i]=(line[i]+(a if pa<=pb and pa<=pc else u if pb<=pc else c))&255
        rows.append(line); prev=line
    return w,h,bpp,rows
def png_write(path,w,h,rows):
    raw=b''.join(b'\0'+bytes(r) for r in rows)
    def ch(t,d): return struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d))
    open(path,'wb').write(b'\x89PNG\r\n\x1a\n'+ch(b'IHDR',struct.pack('>IIBBBBB',w,h,8,0,0,0,0))+ch(b'IDAT',zlib.compress(raw))+ch(b'IEND',b''))
z=zipfile.ZipFile(SRC)
r3=png_decode(open(SRC,'rb').read())[3]
a=png_decode(z.read('share1.png')); b=png_decode(z.read('share2.png'))
w,h,bpp,r1=a; r2=b[3]
print(w,h,bpp, set(r1[0][0::bpp]), set(r1[0][3::bpp]) if bpp==4 else '')
rows=[bytes(x^y^c for x,y,c in zip(l1[0::4],l2[0::4],l3[0::4])) for l1,l2,l3 in zip(r1,r2,r3)] if False else None
for name,f in (('xor',lambda x,y:x^y),('and',lambda x,y:x&y)):
    rows=[bytes(f(x,y) for x,y in zip(l1[0::bpp],l2[0::bpp])) for l1,l2 in zip(r1,r2)]
    png_write(f'{OUT}/{name}.png',w,h,rows)

rows=[bytes(x^y^c for x,y,c in zip(l1[0::bpp],l2[0::bpp],l3[0::bpp])) for l1,l2,l3 in zip(r1,r2,r3)]
png_write(f'{OUT}/xor3.png',w,h,rows)
