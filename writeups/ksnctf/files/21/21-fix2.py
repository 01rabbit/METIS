import struct, random
B='/Users/makoto.sugita/personal/METIS/.metis-state/work/21x/'
pt=open(B+'encrypt.cpp','rb').read(); enc=open(B+'encrypt.enc','rb').read(); fl=open(B+'flag.enc','rb').read()
A=0x9908b0df; U=0x80000000; L=0x7fffffff
def untemper(y):
    y^=y>>18; y^=(y<<15)&0xefc60000
    t=y
    for _ in range(5): t=y^((t<<7)&0x9d2c5680)
    y=t;t=y
    for _ in range(3): t=y^(t>>11)
    return t&0xffffffff
ks=[struct.unpack('<I',enc[4+4*i:8+4*i])[0]^struct.unpack('<I',pt[4*i:4*i+4])[0] for i in range(650)]
st=[untemper(k) for k in ks[:624]]
def decrypt(st):
    r=random.Random(); r.setstate((3,tuple(st)+(624,),None))
    for _ in range(26): r.getrandbits(32)
    FL=struct.unpack('<I',fl[:4])[0]; out=bytearray()
    for i in range((FL+3)//4):
        out+=struct.pack('<I',struct.unpack('<I',fl[4+4*i:8+4*i])[0]^r.getrandbits(32))
    return bytes(out[:FL])
W=lambda d,f: struct.unpack('<I',d[4*f:4*f+4])[0]
log=[]
for it in range(200):
    d=decrypt(st); done=True
    for i in [x for x in range(48,624) if not 560<=x<=567]:
        E=W(d,i-26)
        if not E: continue
        e=untemper(E)
        if i<227:
            st[i+397]^=e; log.append(('src',i+397,hex(untemper(e) if 0 else e)))
        else:
            if e>>31: y=(((e^A)<<1)&0xffffffff)|1
            else: y=(e<<1)&0xffffffff
            st[i]^=y&U; st[(i+1)%624]^=y&L; log.append(('y',i,hex(y)))
        done=False; break
    if done: break
print('iterations',it); print(log)
d=decrypt(st); open(B+'flag3.jpg','wb').write(d); print(d[-2:].hex())
