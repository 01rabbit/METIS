import zlib, itertools, sys
d=open('/Users/makoto.sugita/personal/METIS/.metis-state/.metis-artifacts-rrmq7s9n/01-00-flag.zip','rb').read()
hdr=d[30+9:30+9+12]; body=d[30+9+12:30+9+316]; CRC=0xd66cb67b
T=[]
for i in range(256):
    c=i
    for _ in range(8): c=(c>>1)^0xEDB88320 if c&1 else c>>1
    T.append(c)
def cr(c,b): return (c>>8)^T[(c^b)&255]
def dec(pw,data):
    k0,k1,k2=0x12345678,0x23456789,0x34567890
    for b in pw: 
        k0=cr(k0,b); k1=((k1+(k0&255))*134775813+1)&0xffffffff; k2=cr(k2,k1>>24)
    out=bytearray()
    for c in data:
        t=(k2|2)&0xffff; p=c^(((t*(t^1))>>8)&255)
        k0=cr(k0,p); k1=((k1+(k0&255))*134775813+1)&0xffffffff; k2=cr(k2,k1>>24); out.append(p)
    return bytes(out)
def test(pw):
    h=dec(pw,hdr)
    if h[11]!=0x91 and h[11]!=0xd6: return None
    p=dec(pw,hdr+body)[12:]
    return p if zlib.crc32(p)==CRC else None
words=open(sys.argv[1]).read().split() if len(sys.argv)>1 else []
cands=[w.encode() for w in words]
cands+= [str(i).encode() for i in range(10**6)]
cands+= [str(i).zfill(n).encode() for n in range(1,8) for i in range(10**n)]
for pw in cands:
    r=test(pw)
    if r: print(pw,r[:300]); break
else: print('none',len(cands))
