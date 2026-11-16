import re,html,glob
def nums(t):
    t=html.unescape(re.sub(r'<[^>]+>','\n',t)); return [int(x) for x in re.findall(r'\b\d{20,}\b',t)]
def iroot(x,k):
    lo,hi=0,1<<(x.bit_length()//k+2)
    while lo<hi:
        m=(lo+hi+1)//2
        if m**k<=x: lo=m
        else: hi=m-1
    return lo
for p in glob.glob('.metis-state/.metis-artifacts-*/00-problem.html'):
    t=open(p,'rb').read().decode('utf-8','replace')
    if 'Math I' in t and 'Shor' in t and 'Math II' not in t.split('Math II')[0][-0:0]:
        if 'Released at: 2012/06/02' in t and 'Shor' in t:
            n,c,pp,q=nums(t)[:4] if len(nums(t))>=4 else (None,)*4
            ns=nums(t); print('M1',p,len(ns))
            n,c,pp,q=ns[0],ns[1],ns[2],ns[3]
            assert pp*q==n
            d=pow(65537,-1,(pp-1)*(q-1)); m=pow(c,d,n)
            print(m); print(("%0512x"%m)); print(bytes.fromhex("%0512x"%m).strip(b'\0'))
    if 'FLAG_' in t and 'modulo arithmetic' in t:
        x=nums(t)[0]; y=iroot(x,101); print('M2',p,y**101==x); print(y)
