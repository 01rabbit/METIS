import struct,re
d=open('/Users/makoto.sugita/personal/METIS/.metis-state/work/24x/rightsout.bin','rb').read()
# find method headers: tiny (low 2 bits 0b10) or fat (0b11). Scan section .text 0x200..0x1998
one={0x00:'nop',0x01:'break',0x02:'ldarg.0',0x03:'ldarg.1',0x04:'ldarg.2',0x05:'ldarg.3',0x06:'ldloc.0',0x07:'ldloc.1',0x08:'ldloc.2',0x09:'ldloc.3',0x0a:'stloc.0',0x0b:'stloc.1',0x0c:'stloc.2',0x0d:'stloc.3',
0x14:'ldnull',0x15:'ldc.i4.m1',0x16:'ldc.i4.0',0x17:'ldc.i4.1',0x18:'ldc.i4.2',0x19:'ldc.i4.3',0x1a:'ldc.i4.4',0x1b:'ldc.i4.5',0x1c:'ldc.i4.6',0x1d:'ldc.i4.7',0x1e:'ldc.i4.8',
0x25:'dup',0x26:'pop',0x2a:'ret',0x58:'add',0x59:'sub',0x5a:'mul',0x5b:'div',0x5d:'rem',0x5f:'and',0x60:'or',0x61:'xor',0x62:'shl',0x63:'shr',0x8e:'ldlen',0x90:'ldelem.i1',0x91:'ldelem.u1',0x94:'ldelem.i4',0x9c:'stelem.i1',0x9e:'stelem.i4',0xa2:'stelem.ref',0x9a:'ldelem.ref',0xd1:'conv.u2',0xd2:'conv.u1',0x69:'conv.i4',0xd4:'conv.i',0x6e:'conv.u8',0x6a:'conv.i8',0x28:None}
b1={0x0e:'ldarg.s',0x0f:'ldarga.s',0x10:'starg.s',0x11:'ldloc.s',0x12:'ldloca.s',0x13:'stloc.s',0x1f:'ldc.i4.s',0x2b:'br.s',0x2c:'brfalse.s',0x2d:'brtrue.s',0x2e:'beq.s',0x2f:'bge.s',0x30:'bgt.s',0x31:'ble.s',0x32:'blt.s',0x33:'bne.un.s',0x34:'bge.un.s',0x35:'bgt.un.s',0x36:'ble.un.s',0x37:'blt.un.s'}
b4={0x20:'ldc.i4',0x28:'call',0x6f:'callvirt',0x72:'ldstr',0x73:'newobj',0x7b:'ldfld',0x7c:'ldflda',0x7d:'stfld',0x7e:'ldsfld',0x80:'stsfld',0x8d:'newarr',0x38:'br',0x39:'brfalse',0x3a:'brtrue',0x3b:'beq',0x3c:'bge',0x3d:'bgt',0x3e:'ble',0x3f:'blt',0x40:'bne.un',0x41:'bge.un',0x42:'bgt.un',0x43:'ble.un',0x44:'blt.un',0x74:'castclass',0x75:'isinst',0xd0:'ldtoken',0x7f:'ldsflda',0x8c:'box',0xa3:'ldelem',0xa4:'stelem',0x27:'jmp'}
def dis(code):
    i=0;out=[]
    while i<len(code):
        op=code[i];o=i;i+=1
        if op==0xfe:
            op2=code[i];i+=1
            nm={0x01:'ceq',0x02:'cgt',0x04:'clt',0x16:'constrained'}.get(op2,'fe%02x'%op2)
            if op2==0x16: i+=4
            out.append((o,nm));continue
        if op in b4:
            v=struct.unpack('<i',code[i:i+4])[0];i+=4
            if op in (0x38,0x39,0x3a,0x3b,0x3c,0x3d,0x3e,0x3f,0x40,0x41,0x42,0x43,0x44): out.append((o,b4[op],'IL_%04x'%(i+v)))
            else: out.append((o,b4[op],hex(v&0xffffffff)))
        elif op in b1:
            v=code[i];i+=1
            if op>=0x2b: 
                s=v-256 if v>127 else v; out.append((o,b1[op],'IL_%04x'%(i+s)))
            else: out.append((o,b1[op],v))
        elif op in one and one[op]: out.append((o,one[op]))
        else: out.append((o,'op%02x'%op))
    return out
# scan for method headers
for off in range(0x200,0x1990):
    h=d[off]
    if h&3==2:
        n=h>>2
        if 3<=n<=300 and d[off+n]==0x2a:
            pass
res=[]
import sys
# fat headers
for off in range(0x200,0x1990,4):
    f=struct.unpack('<H',d[off:off+2])[0]
    if f&0xf==0x3 and (f>>12)==3:
        size=struct.unpack('<I',d[off+4:off+8])[0]
        if 0<size<4000 and d[off+12+size-1]==0x2a:
            res.append((off,'fat',size,d[off+12:off+12+size]))
for off in range(0x200,0x1990):
    if d[off]&3==2:
        n=d[off]>>2
        if 1<=n<=63 and d[off+n]==0x2a and not any(off<r[0]+12+r[2] and off>=r[0] for r in res): res.append((off,'tiny',n,d[off+1:off+1+n]))
res.sort()
for off,k,n,code in res:
    print('== method @',hex(off),k,n)
    for ins in dis(code): print('  IL_%04x %s %s'%(ins[0],ins[1],' '.join(map(str,ins[2:]))))
