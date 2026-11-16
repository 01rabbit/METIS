"""Decrypt stored ZipCrypto entries of a zip given the key state after the password (x y z hex).
Usage: python3 -I 19-decrypt.py ZIP XHEX YHEX ZHEX OUTDIR
Parses local headers sequentially (sizes taken from local headers; data descriptors skipped when present).
Writes decrypted entries into OUTDIR (must be a fresh scratch dir) and prints CRC check per entry."""
import struct, sys, zlib, os
T=[]
for i in range(256):
    c=i
    for _ in range(8): c=(c>>1)^0xEDB88320 if c&1 else c>>1
    T.append(c)
def cr(c,b): return (c>>8)^T[(c^b)&255]
def decrypt(data, keys):
    x,y,z=keys; out=bytearray()
    for c in data:
        t=(z|2)&0xffff; p=c^(((t*(t^1))>>8)&255)
        x=cr(x,p); y=((y+(x&255))*134775813+1)&0xffffffff; z=cr(z,y>>24); out.append(p)
    return bytes(out)
def main():
    zp,xh,yh,zh,outdir=sys.argv[1:6]
    keys=(int(xh,16),int(yh,16),int(zh,16))
    d=open(zp,'rb').read(); p=0; os.makedirs(outdir,exist_ok=True)
    while d[p:p+4]==b'PK\x03\x04':
        v,fl,m,t,dt,crc,cs,us,nl,el=struct.unpack('<HHHHHIIIHH',d[p+4:p+30])
        name=d[p+30:p+30+nl].decode('latin1'); s=p+30+nl+el
        raw=decrypt(d[s:s+cs],keys)[12:]
        ok=(m==0 and zlib.crc32(raw)==crc)
        print(name,'method',m,'crc_ok',ok,len(raw))
        open(os.path.join(outdir,os.path.basename(name)),'wb').write(raw)
        p=s+cs
        if fl&8 and d[p:p+4]==b'PK\x07\x08': p+=16
main()
