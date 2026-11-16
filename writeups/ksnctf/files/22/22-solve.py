rows="""oomktvziqtaovmmpxzoqrzsxlpwpgoj
uDQEMISYnnVYnvyWRhHsDXnSCXAVVZj
tZbknedErdpvAwQWpUiLqOxIqpafvXp
dXoAVWcKppbEPuaqmXWjXJwRoRFOoEg
pDiRUXlQjKJlslskVpGwtljGyVJPxHv
bQsQNKxCsdYMdQPJiBmyrsuOrJQOtXg
pMekeinUaMoDXqFzweLKipkBuggnsUv
eQFYCJSKfBgHaJgZnZoWmOmAOJLVQHi
hljrplajyKNXtwmfOjRwOqcqeeplyzy
gkFOltsOyrPgIaerIaSjQQaVMyEhfyd
vEaRHbBzfrcwJbCZmHdddLpuEJwspbt
sXQGkwpKaTZmWJiZzpbkpHNiToawxKn
wJpIKbGhnLjVAJNcxrqkKEJCKCOocSv
mTRDNDpFtRUmcHoRELeSqXoGUIIsuYu
ajeHaSVlQGLaEprSQarDzTomJdAWfqb
zIJLHRBXMvNDegYeaoVRDuWBbdSBtLv
xIeKdAYwajGHMgRLDGgDinBiLNBgatb
kHepNsCQSJjTRmQrCHYWJqIPOVAUOer
rvhmZfmogPglGNuLyAuSivBctlvVfzb
qBJdHUkSaTArlgkhtHPyGhXOPkwmkBq
rvbzZfwvLtTnhyXVHPlwsuGZQnNiNcm
yCMtAVwYVgtZHVNznolGMBETIHFmoWj
wfezbysbvOzsAhxSZFFAfOouyHldEYh
gNHKKSFUtcUxfRyXHMugYBtAxBwDJZh
rHmsozuNeoJqyzMDHsNbUDwzaNLtdxr
bVmQMHyNndOWCZLnhrPxZXCYLDTWQre
aSiEEJjZtoRpUzgsxsiiGzvnRpKLMrk
qTzGCKvNhUhjrmCjAdwQAvkgqHyJZLm
sSxzwjxAnWesTszIxirRwcWIXUPtwwa
nTDEMTRGyhzdCtkTTDWbxdSjsNYlfXz
eawtidzosgaofjxxyfcdoiulemirqap""".split()
n=len(rows); print(n,{len(r) for r in rows})
g=[list(r) for r in rows]
# layers: ring k lowercase? print lowercase mask
for r in rows: print(''.join('.' if c.isupper() else c for c in r))
import itertools
low=lambda s:s.lower()
def spiral(g,start,cw):
    n=len(g); seen=set(); out=[]
    # build by peeling
    import copy
    gg=[r[:] for r in g]
    # generate coordinates clockwise from top-left
    coords=[]
    t,l,b,r=0,0,n-1,n-1
    while t<=b and l<=r:
        for x in range(l,r+1): coords.append((t,x))
        for y in range(t+1,b+1): coords.append((y,r))
        if t<b:
            for x in range(r-1,l-1,-1): coords.append((b,x))
        if l<r:
            for y in range(b-1,t,-1): coords.append((y,l))
        t+=1;l+=1;b-=1;r-=1
    return coords
co=spiral(g,0,1)
s=''.join(g[y][x] for y,x in co)
print('spiral cw TL:',s)
print('reverse:',s[::-1])
# transposed grid spiral (ccw)
gt=[list(c) for c in zip(*g)]
print('spiral ccw TL:',''.join(gt[y][x] for y,x in co))
# lowercase-only extraction in row order
print('lowercase row-major:',''.join(c for r in rows for c in r if c.islower()))
print('lowercase col-major:',''.join(c for col in zip(*rows) for c in col if c.islower()))
print('UPPER row-major:',''.join(c for r in rows for c in r if c.isupper()))
