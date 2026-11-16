# Sigma(Secret): per 8-byte block server prints [x+y, x^2+y^2], y=2^32+lo.
# Recover x,y from power sums: xy=(s1^2-s2)/2; roots of t^2 - s1 t + xy.
import ast,sys
from math import isqrt
OFF=1<<32; out=b""
for line in sys.stdin:          # feed the server's printed lists on stdin
    line=line.strip()
    if not line.startswith("["): continue
    s1,s2=ast.literal_eval(line)
    xy=(s1*s1-s2)//2; r=isqrt(s1*s1-4*xy)
    x=(s1-r)//2; y=(s1+r)//2
    if not (x<OFF<=y): x,y=y,x
    out+=x.to_bytes(4,"big")+(y-OFF).to_bytes(4,"big")
print(out.split(b"\x00")[0])
