import hashlib,struct,sys
d=open(sys.argv[1],"rb").read()
print(d[0x98070:0x98080].hex())
K1=0x3233504c49; K2=0x4942412d323378
tab=[d[0xc30e0+16*i:0xc30e0+16*i+16] for i in range(40)]
pairs=[]
for i in range(40):
    c=[(a,b) for a in range(256) for b in range(256)
       if hashlib.md5(struct.pack("<Q",((((a<<8)|b)*K1)^K2)&(2**64-1))).digest()==tab[i]]
    pairs.append(c)
print(pairs)
s=bytes([pairs[0][0][0]])+bytes(p[0][1] for p in pairs)
print(s)
