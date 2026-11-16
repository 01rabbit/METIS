"""Step 4: cluster->hex map, assemble T, RS(255,64) decode (roots alpha^0..alpha^190, symbols are LOG-encoded bytes per ecc.py)."""
import numpy as np
W='/Users/makoto.sugita/personal/METIS/.metis-state/work/'
lab=np.load(W+'34-lab2.npy'); bb=np.load(W+'34-feat.npz')['bb']
mp="BC464DE2779A?0?366BC5809 0 E".replace(' ','')
# index -> char (read from montage of 48 clusters)
M="B C 4 6 4 D E 2 7 7 8 A 9 0 3 6 B C 5 8 0 9 0 E 0 3 3 0 A 1 F 5 9 0 4 B 2 3 4 8 0 7 1 0 6 D 6 8".split()
assert len(M)==48
hexs=[M[l] for l in lab]
print(''.join(hexs[:32]))
txt=''.join(hexs)
n=475*255
T=bytes(int(txt[2*i:2*i+2],16) for i in range(n))
# GF(256) 0x11d
A=[1]
for _ in range(254):
    a=A[-1]<<1
    if a>>8: a^=0x11d
    A.append(a)
Ai={v:i for i,v in enumerate(A)}
def mul(a,b): return 0 if a==0 or b==0 else A[(Ai[a]+Ai[b])%255]
def inv(a): return A[(255-Ai[a])%255]
def val(b): return 0 if b==255 else A[b]
def lg(v): return 255 if v==0 else Ai[v]
def pev(p,x):  # p[j] coeff of x^j
    r=0
    for c in reversed(p): r=mul(r,x)^c
    return r
NP=191
def decode(c):
    S=[pev(c,A[i]) for i in range(NP)]
    if not any(S): return c,0
    # Berlekamp-Massey
    L=0; Lam=[1]; B=[1]; m=1; b=1
    for n_ in range(NP):
        d=S[n_]
        for i in range(1,L+1):
            if i<len(Lam): d^=mul(Lam[i],S[n_-i])
        if d==0: m+=1; continue
        T_=Lam[:]
        coef=mul(d,inv(b))
        Lam=Lam+[0]*(len(B)+m-len(Lam))
        for i,x in enumerate(B): Lam[i+m]^=mul(coef,x)
        if 2*L<=n_: L=n_+1-L; B=T_; b=d; m=1
        else: m+=1
    Lam=Lam[:L+1]
    pos=[j for j in range(255) if pev(Lam,A[(255-j)%255])==0]
    if len(pos)!=L: raise ValueError('bm fail')
    Om=[0]*NP
    for i in range(NP):
        for j,l in enumerate(Lam):
            if i+j<NP: Om[i+j]^=mul(S[i],l)
        # Omega = S*Lam mod x^NP
    dLam=[Lam[i] if i%2==1 else 0 for i in range(1,len(Lam))]  # formal derivative coefficients (char 2): coefficient of x^(i-1)
    c=c[:]
    for j in pos:
        Xinv=A[(255-j)%255]
        num=pev(Om,Xinv); den=pev(dLam,Xinv)
        e=mul(A[j],mul(num,inv(den)))  # b=0 -> X^(1-b)
        c[j]^=e
    assert not any(pev(c,A[i]) for i in range(NP)), 'residual'
    return c,len(pos)
D=T[:475*64]; E=T[475*64:]
out=bytearray(); errs=[]; bad=0
for k in range(475):
    cw=[0]*255
    par=E[191*k:191*k+191]; dat=D[64*k:64*k+64]
    for i in range(191): cw[i]=val(par[i])
    for j in range(64): cw[191+j]=val(dat[j])
    try:
        c,ne=decode(cw)
    except Exception as ex:
        bad+=1; ne=-1; c=cw
    errs.append(ne)
    out+=bytes(lg(c[191+j]) for j in range(64))
print('failed blocks',bad,'max errs',max(errs),'mean',sum(e for e in errs if e>=0)/475)
open(W+'34-flag.jpg','wb').write(bytes(out))
print(out[:12].hex())
