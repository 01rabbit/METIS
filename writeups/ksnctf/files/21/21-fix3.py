import struct
exec(open('/Users/makoto.sugita/personal/METIS/.metis-state/work/21-fix2.py').read().split("log=[]")[0])
d0=decrypt(st)
E={i:(W(d0,i-26) if i>=26 else 0) for i in range(624)}
ep={i:untemper(E[i]) for i in E}
bad=set(range(26,48))|set(range(560,568))   # real plaintext, no information
def ydec(D): return (((D^A)<<1)&0xffffffff)|1 if D>>31 else (D<<1)&0xffffffff
eo=[0]*624
y={}
for i in range(228,624):
    if i in bad or (i-227) in bad: continue
    y[i]=ydec(ep[i]^ep[i-227])
for j in range(229,624):
    if j in y and (j-1) in y: eo[j]=(y[j]&U)|(y[j-1]&L)
y2={}
for i in range(48,227):
    if (i+397) in bad: continue
    y2[i]=ydec(ep[i]^eo[i+397])
for j in range(49,228):
    if j in y2 and (j-1) in y2: eo[j]=(y2[j]&U)|(y2[j-1]&L)
print({j:hex(v) for j,v in enumerate(eo) if v})
st2=[s^e for s,e in zip(st,eo)]
d=decrypt(st2); open(B+'flag4.jpg','wb').write(d); print(d[-2:].hex())
