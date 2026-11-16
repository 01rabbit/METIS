import struct
d=open('.metis-state/.metis-artifacts-ycc43r1h/01-00-Riddle.exe','rb').read()
def rc4(k,b):
    S=list(range(256));j=0
    for i in range(256):
        j=(j+S[i]+k[i%len(k)])&255;S[i],S[j]=S[j],S[i]
    i=j=0;o=bytearray()
    for c in b:
        i=(i+1)&255;j=(j+S[i])&255;S[i],S[j]=S[j],S[i];o.append(c^S[(S[i]+S[j])&255])
    return bytes(o)
key=b'M6eMYngDGFbYE9HQ'
base=0x3a00-0x5000
for i in range(4):
    va=0x405178+40*i-0x400000
    rec=d[va+base:va+base+40]
    ptr=struct.unpack_from('<I',rec,0)[0]
    ln=struct.unpack_from('<I',rec,0x24)[0]
    print(i,hex(ptr),ln,rc4(key,rec[4:4+ln]))
