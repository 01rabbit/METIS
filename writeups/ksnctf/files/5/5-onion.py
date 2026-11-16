import re,sys,base64
h=open(sys.argv[1],encoding='utf-8').read()
txt=re.sub(r'<[^>]+>','\n',h)
d=''.join(l.strip() for l in txt.split('\n') if re.fullmatch(r'[A-Za-z0-9+/=]{40,}',l.strip())).encode()
n=0
while True:
    try: x=base64.b64decode(d,validate=True)
    except Exception: break
    d=re.sub(rb'\s',b'',x) if re.fullmatch(rb'[A-Za-z0-9+/=\s]+',x) else x
    n+=1
    if d is x: break
print(n,d.decode())
import binascii
body=d.decode().split('\n')
print(b''.join(binascii.a2b_uu(l) for l in body[1:] if l.strip() and l.strip()!='end' and l.strip()!='`').decode())
