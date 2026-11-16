import struct
from capstone import *
d=open('/Users/makoto.sugita/personal/METIS/.metis-state/.metis-artifacts-a2_k_ca7/01-00-livesout.exe','rb').read()
code=d[0x400:0x400+0x10c2]
cs=Cs(CS_ARCH_X86,CS_MODE_64)
for i in cs.disasm(code,0x140001000):
    print(hex(i.address)[2:],i.mnemonic,i.op_str)
