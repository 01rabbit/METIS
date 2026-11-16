# Alpha2-style (SkyLined mixedcase) decoder re-implemented; never executes payload.
# loop: out[k] = ((c[2k]*0x10)&0xff) ^ c[2k+1]  (imm 0x51 gets patched to 0x10 by xor [ecx+0x30],0x41)
import re,sys
from capstone import *
t=open('/Users/makoto.sugita/personal/METIS/.metis-state/.metis-artifacts-3eosju20/00-problem.html',encoding='utf8',errors='replace').read()
s=re.findall(r'\n(VTX630[A-Za-z0-9]+)\n',t)[0].encode()
sin=107
pairs=[]
k=0
while s[sin+2*k]!=0x41 or True:
    if sin+2*k+1>=len(s) or s[sin+2*k]==0x41: break
    pairs.append(((s[sin+2*k]*0x10)&0xff)^s[sin+2*k+1]);k+=1
o=bytes(pairs)
open('/private/tmp/claude-502/-Users-makoto-sugita-personal-METIS/05385c51-614d-419f-b402-93fdc078644d/scratchpad/w/dec.bin','wb').write(o)
print(len(o),o.hex())
for i in Cs(CS_ARCH_X86,CS_MODE_32).disasm(o,0):print(hex(i.address),i.bytes.hex(),i.mnemonic,i.op_str)
# message string = pushes (little-endian) reversed; byte [esp+0x15] nulled
import struct
pushes=[0x47414c46,0x5048325f,0x34337476,0x436b6179,0x72386f36,0x20205875][:]
pushes=[struct.unpack('<I',o[o.index(b'\x68'+struct.pack('<I',v))+1:][:4])[0] for v in pushes]
msg=b''.join(struct.pack('<I',v) for v in pushes)[:0x15]
print(msg.decode())
