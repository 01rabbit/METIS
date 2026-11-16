import struct, random, sys
d='/Users/makoto.sugita/personal/METIS/.metis-state/work/21x/'
pt=open(d+'encrypt.cpp','rb').read(); enc=open(d+'encrypt.enc','rb').read(); fl=open(d+'flag.enc','rb').read()
L=struct.unpack('<I',enc[:4])[0]; assert L==len(pt),(L,len(pt))
pt+=b'\0'*(-len(pt)%4)
nw=len(pt)//4
ks=[struct.unpack('<I',enc[4+4*i:8+4*i])[0]^struct.unpack('<I',pt[4*i:4*i+4])[0] for i in range(nw)]
def untemper(y):
    y^=y>>18
    y^=(y<<15)&0xefc60000
    t=y
    for _ in range(5): t=y^((t<<7)&0x9d2c5680)
    y=t
    t=y
    for _ in range(3): t=y^(t>>11)
    return t&0xffffffff
st=[untemper(k) for k in ks[:624]]
r=random.Random(); r.setstate((3,tuple(st)+(624,),None))
# verify
for i in range(624,nw): assert r.getrandbits(32)==ks[i],i
print('MT state recovered, verified on',nw-624,'extra words')
FL=struct.unpack('<I',fl[:4])[0]
out=bytearray()
for i in range((FL+3)//4):
    c=struct.unpack('<I',fl[4+4*i:8+4*i])[0]
    out+=struct.pack('<I',c^r.getrandbits(32))
open(d+'flag.jpg','wb').write(out[:FL]); print(out[:4].hex(),FL)
