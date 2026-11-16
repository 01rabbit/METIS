import re
from math import gcd
long_to_bytes=lambda x:x.to_bytes((x.bit_length()+7)//8,"big")
d=dict(re.findall(r'(\w+) = (\d+)',open('/private/tmp/claude-502/-Users-makoto-sugita-personal-METIS/d898862a-22fc-4326-ad27-cc093443114d/scratchpad/ch/almost-shared-prime/almost-shared-prime/output.txt').read()))
n1,n2,c1,c2=[int(d[k]) for k in('n1','n2','c1','c2')]
# n2/n1 ~ q2/q1 (rel err 2/p): find convergent
a,b=n2,n1;h0,h1,k0,k1=0,1,1,0
while b:
    t=a//b;a,b=b,a-t*b
    h0,h1=h1,t*h1+h0;k0,k1=k1,t*k1+k0
    if k1.bit_length()>256: break
    if n1%k1==0 and k1.bit_length()>=255:
        q1=k1;p=n1//q1
        if n2%(p+2)==0:
            q2=n2//(p+2);print(q1.bit_length(),q2.bit_length())
            phi=(p-1)*(q1-1);m=pow(c1,pow(65537,-1,phi),n1);print(long_to_bytes(m));break
