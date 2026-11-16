# Shared Prime: n1=p*q1, n2=p*q2 share prime p -> gcd factors both.
import re,math
s=open("output.txt").read()
V={k:int(re.search(rf"{k} = (\d+)",s).group(1)) for k in("n1","n2","c1","c2")}
p=math.gcd(V["n1"],V["n2"]); e=65537
q=V["n1"]//p; d=pow(e,-1,(p-1)*(q-1)); m=pow(V["c1"],d,V["n1"])
print(bytes.fromhex(f"{m:x}"))
