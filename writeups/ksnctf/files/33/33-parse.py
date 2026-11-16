import struct,sys
from collections import defaultdict
f=open(sys.argv[1],'rb').read()
magic=f[:4]; en='<' if magic in (b'\xd4\xc3\xb2\xa1',b'\x4d\x3c\xb2\xa1') else '>'
lt=struct.unpack(en+'I',f[20:24])[0]
o=24; streams=defaultdict(list)
while o<len(f):
    ts,tu,cl,ol=struct.unpack(en+'IIII',f[o:o+16]); p=f[o+16:o+16+cl]; o+=16+cl
    if lt==1: p=p[14:]
    elif lt==113: p=p[16:]
    if p[0]>>4!=4: continue
    ihl=(p[0]&15)*4; src=p[12:16]; dst=p[16:20]
    tcp=p[ihl:]; sp,dp,seq=struct.unpack('>HHI',tcp[:8]); doff=(tcp[12]>>4)*4
    pay=tcp[doff:struct.unpack('>H',p[2:4])[0]-ihl]
    if pay: streams[(src,sp,dst,dp)].append((seq,pay))
out={}
for k,v in streams.items():
    seen={};
    for s,pl in v: seen.setdefault(s,pl)
    data=b'';
    for s in sorted(seen): data+=seen[s]
    out[k]=data
    print(k[0].hex(),k[1],'->',k[2].hex(),k[3],len(data),len(v))
import pickle;pickle.dump(out,open(sys.argv[2],'wb'))
