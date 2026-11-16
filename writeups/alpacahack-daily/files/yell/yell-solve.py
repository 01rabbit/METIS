import re,math,sys
long_to_bytes=lambda v: v.to_bytes((v.bit_length()+7)//8,"big")
d=sys.argv[1]
t=open(d).read()
cands=eval(re.search(r'cands= (\[.*?\])',t).group(1))
n=int(re.search(r'n= ?=? ?(\d+)',t).group(1)) if False else int(re.search(r'\nn= (\d+)',t).group(1))
c=int(re.search(r'\nc= (\d+)',t).group(1))
L=1
for i in range(1,256): L=L*i//math.gcd(L,i)
P=math.prod(cands)
for x in cands:
    E=L*(P//x)
    g=math.gcd(pow(2,E,n)-1,n)
    if 1<g<n:
        p=g;q=n//g;break
d=pow(0x10001,-1,(p-1)*(q-1))
print(long_to_bytes(pow(c,d,n)))
