"""Generate a synthetic ZipCrypto sample to validate 19-zipattack.c. Prints args for the C tool."""
import random, sys
T=[]
for i in range(256):
    c=i
    for _ in range(8): c=(c>>1)^0xEDB88320 if c&1 else c>>1
    T.append(c)
def cr(c,b): return (c>>8)^T[(c^b)&255]
def ks(z):
    t=(z|2)&0xffff; return ((t*(t^1))>>8)&255
seed=int(sys.argv[1]) if len(sys.argv)>1 else 1
random.seed(seed)
pw=bytes(random.randrange(33,127) for _ in range(random.randrange(5,12)))
x,y,z=0x12345678,0x23456789,0x34567890
def upd(b):
    global x,y,z
    x=cr(x,b); y=((y+(x&255))*134775813+1)&0xffffffff; z=cr(z,y>>24)
for b in pw: upd(b)
init=(x,y,z)
plain=bytes(random.randrange(256) for _ in range(12))+bytes.fromhex('ffd8ffe000104a46494600010101')[:12]
plain=bytes(random.randrange(256) for _ in range(12))+bytes.fromhex('ffd8ffe000104a4649460001')
ct=b''
zs=[]
for p in plain:
    zs.append(z)
    ct+=bytes([p^ks(z)]); upd(p)
print(ct.hex(), plain[12:].hex(), 12, 0, 1, zs[12+11]>>16, '#init', '%08x %08x %08x'%init, file=sys.stderr)
print(ct.hex(), plain[12:].hex(), 12, 0, 1, zs[12+11]>>16)
