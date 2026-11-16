import struct,capstone
d=open('.metis-state/.metis-artifacts-ycc43r1h/01-00-Riddle.exe','rb').read()
pe=struct.unpack_from('<I',d,0x3c)[0]
ns=struct.unpack_from('<H',d,pe+6)[0]; osz=struct.unpack_from('<H',d,pe+20)[0]
base=struct.unpack_from('<I',d,pe+52)[0]
secs=[]
o=pe+24+osz
for i in range(ns):
    n,vs,va,rs,rp=struct.unpack_from('<8sIIII',d,o+40*i); secs.append((n,vs,va,rs,rp)); print(n,hex(va),hex(rp))
print(hex(base))
text=secs[0]
code=d[text[4]:text[4]+text[3]]
md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
import sys
targets=[0x2678,0x2690,0x2818,0x282c]  # file offs; rdata va=?
rd=secs[1]
for t in targets: print(hex(t), hex(base+rd[2]+t-rd[4]))
ins=list(md.disasm(code,base+text[2]))
open('.metis-state/work/11-dis.txt','w').write('\n'.join(f'{i.address:x} {i.mnemonic} {i.op_str}' for i in ins))
