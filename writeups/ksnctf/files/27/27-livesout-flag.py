# Lives out (ksnctf 27): statically derive the message built when all 16x16 Life cells are dead.
# out[n] = ((A[n]-S[n]) ^ X[n]) + Add[n]  (16-bit), 21 UTF-16 chars, arrays of dwords on stack frame (rbp-based)
import struct
from capstone import *
d=open('/Users/makoto.sugita/personal/METIS/.metis-state/.metis-artifacts-a2_k_ca7/01-00-livesout.exe','rb').read()
IB=0x140000000
secs=[(0x1000,0x10c2,0x400),(0x3000,0xbe0,0x1600),(0x4000,0x738,0x2200)]
def rd(va,n):
    r=va-IB
    for a,s,o in secs:
        if a<=r<a+s:return d[o+r-a:o+r-a+n]
cs=Cs(CS_ARCH_X86,CS_MODE_64);cs.detail=True
code=d[0x400:0x400+0x10c2]
mem={}  # rbp offset -> byte
x={}
for i in cs.disasm(code,IB+0x1000):
    if not (0x140001567<=i.address<=0x1400016b0):continue
    if i.mnemonic=='mov' and 'dword ptr [rbp' in i.op_str:
        off=int(i.op_str.split('rbp')[1].split(']')[0].replace(' ',''),16 if '0x' in i.op_str else 10) if False else None
        o=i.operands[0].mem.disp; v=i.operands[1].imm
        for k in range(4):mem[o+k]=(v>>(8*k))&255
    elif i.mnemonic=='movdqa':
        o0,o1=i.operands
        if o1.type==1 and False:pass
        if o0.type==1: # reg <- mem rip
            va=i.address+i.size+o1.mem.disp
            x[i.reg_name(o0.reg)]=rd(va,16)
        else:
            o=o0.mem.disp
            v=x[i.reg_name(o1.reg)]
            for k in range(16):mem[o+k]=v[k]
def arr(base,n=21):return [struct.unpack('<I',bytes(mem[base+4*k+j] for j in range(4)))[0] for k in range(n)]
S=arr(-0x20);X=arr(0x40);A=arr(0xa0);AD=arr(0x100)
out=''.join(chr((((a-s)&0xffff)^xx)+ad&0xffff) for a,s,xx,ad in zip(A,S,X,AD))
print(out)
