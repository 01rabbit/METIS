import struct,re,sys
src=open(sys.argv[1],'rb').read().decode()
# string literal s: concatenated pieces; compute strlen by parsing literals in order
body=src[src.index('s\t='):src.index(';',src.index('s\t='))]
lits=re.findall(r'"([^"]*)"',body)
s=''.join(lits).replace('\\t','\t')
out=chr(len(s)&255)
i=0o20000000+0o1000000+0o600000+0o40000+0o7000+0o500+0o20+0o2
out+=struct.pack('<I',i).split(b'\0')[0].decode()
l=(2*11*229*614741*9576751+5)%2**64
out+=struct.pack('<Q',l).split(b'\0')[0].decode()
from decimal import Decimal
f=struct.pack('<f',float('1.0962664770776731080774868826855754386638240000e-38')).split(b'\0')[0].decode()
d=struct.pack('<d',float('6.7386412564254706622868098890859398199406890000e-308')).split(b'\0')[0].decode()
print(len(s),repr(out+f+d))
print(repr(chr(len(s)&255)),struct.pack('<I',i),struct.pack('<Q',l),struct.pack('<f',float('1.0962664770776731080774868826855754386638240000e-38')),struct.pack('<d',float('6.7386412564254706622868098890859398199406890000e-308')))
