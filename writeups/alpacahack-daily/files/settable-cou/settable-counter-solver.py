import sys
def rl():
    l=sys.stdin.readline()
    sys.stderr.write("<< "+l); return l.strip()
def until(p):
    while True:
        l=rl()
        if p in l: return l
ef=bytes.fromhex(until("encrypted flag").split("=")[1].strip())
n=len(ef)
def send(s):
    sys.stdout.write(s+"\n"); sys.stdout.flush()
send("2"); send(str(2**64-1))
until("Counter")
send("1"); send("00"*(16+n))
l=until("encrypted text")
ks=bytes.fromhex(l.split("=")[1].strip())[16:]
flag=bytes(a^b for a,b in zip(ef,ks))
sys.stderr.write("FLAG "+repr(flag)+"\n")
open(".metis-state/work/settable-counter.candidate","w").write(flag.decode(errors="replace"))
send("0")
