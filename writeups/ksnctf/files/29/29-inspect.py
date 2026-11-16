import struct,zlib,sys,re,os
d=open(sys.argv[1],'rb').read(); out=sys.argv[2]; os.makedirs(out,exist_ok=True)
p=0;files={}
while d[p:p+4]==b'PK\x03\x04':
    _,fl,m,_,_,crc,cs,us,nl,el=struct.unpack('<HHHHHIIIHH',d[p+4:p+30])
    n=d[p+30:p+30+nl].decode('latin1'); s=p+30+nl+el
    raw=d[s:s+cs]; data=zlib.decompress(raw,-15) if m==8 else raw
    files[n]=data; print(n,cs,us,m,hex(fl),'extra',d[p+30+nl:s]); p=s+cs
print('end',p,len(d),d[p:p+40])
for n,v in files.items():
    open(os.path.join(out,n.replace('/','__')),'wb').write(v)
