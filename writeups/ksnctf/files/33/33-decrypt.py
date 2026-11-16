import pickle,struct,math,sys,hmac,hashlib
from cryptography.hazmat.primitives.asymmetric import rsa,padding
S=pickle.load(open(sys.argv[1],'rb'))
ns=pickle.load(open('ns.pkl','rb')) if False else None
def recs(d):
    o=0;r=[]
    while o+5<=len(d):
        t,v,l=struct.unpack('>BHH',d[o:o+5]); r.append((t,v,d[o+5:o+5+l])); o+=5+l
    return r
def hs(b):
    o=0;r=[]
    while o+4<=len(b):
        l=int.from_bytes(b[o+1:o+4],'big'); r.append((b[o],b[o+4:o+4+l])); o+=4+l
    return r
from cryptography import x509
sess={}
for k,d in S.items():
    if k[3]==443:
        sess[k[1]]={'c':recs(d)}
    else:
        sess[k[3]]['s']=recs(d)
mods={}
for p,s in sess.items():
    for t,v,b in s['s']:
        if t==22:
            for ht,hb in hs(b):
                if ht==2: s['sh']=hb; print(p,'ver',hex(v),'sid',hb[35:35+hb[34]].hex())
                if ht==11:
                    cl=int.from_bytes(hb[3:6],'big'); s['n']=x509.load_der_x509_certificate(hb[6:6+cl]).public_key().public_numbers()
    for t,v,b in s['c']:
        if t==22:
            for ht,hb in hs(b):
                if ht==1: s['ch']=hb
                if ht==16: s['cke']=hb[2:]
ns=[(p,s['n'].n,s['n'].e) for p,s in sess.items() if 'n' in s]
(p1,n1,e),(p2,n2,_)=ns
g=math.gcd(n1,n2); print('gcd bits',g.bit_length(),'e',e)
def key(n,p):
    q=n//p;d=pow(e,-1,(p-1)*(q-1))
    return rsa.RSAPrivateNumbers(p,q,d,d%(p-1),d%(q-1),pow(q,-1,p),rsa.RSAPublicNumbers(e,n)).private_key()
def prf(sec,label,seed,n):
    h=len(sec)//2+len(sec)%2; s1,s2=sec[:h],sec[len(sec)-h:]
    def P(h_,s,sd,n):
        out=b'';a=sd
        while len(out)<n:
            a=hmac.new(s,a,h_).digest(); out+=hmac.new(s,a+sd,h_).digest()
        return out[:n]
    a=P(hashlib.md5,s1,label+seed,n);b=P(hashlib.sha1,s2,label+seed,n)
    return bytes(x^y for x,y in zip(a,b))
def rc4(k):
    S_=list(range(256));j=0
    for i in range(256):
        j=(j+S_[i]+k[i%len(k)])%256;S_[i],S_[j]=S_[j],S_[i]
    i=j=0
    def f(data):
        nonlocal i,j
        o=bytearray()
        for c in data:
            i=(i+1)%256;j=(j+S_[i])%256;S_[i],S_[j]=S_[j],S_[i];o.append(c^S_[(S_[i]+S_[j])%256])
        return bytes(o)
    return f
ms={}
for p,s in sess.items():
    if 'cke' not in s: continue
    n=s['n'].n; pp=g; priv=key(n,pp)
    pms=priv.decrypt(s['cke'],padding.PKCS1v15()); print(p,'pms',pms[:2].hex(),len(pms))
    cr=s['ch'][2:34]; sr=s['sh'][2:34]
    m=prf(pms,b'master secret',cr+sr,48); ms[s['sh'][35:35+s['sh'][34]]]=m; s['ms']=m
for p,s in sess.items():
    if 'ms' not in s:
        sid=s['sh'][35:35+s['sh'][34]]; s['ms']=ms[sid]; print(p,'resumed')
    cr=s['ch'][2:34]; sr=s['sh'][2:34]
    kb=prf(s['ms'],b'key expansion',sr+cr,2*16+2*16)
    cmk,smk,ck,sk=kb[:16],kb[16:32],kb[32:48],kb[48:64]
    for who,key_,recl in (('C',ck,s['c']),('S',sk,s['s'])):
        f=rc4(key_); first=True; out=b''
        started=False
        for t,v,b in recl:
            if t==20: started=True; continue
            if started and t in (22,23):
                pt=f(b)[:-16]
                if t==23: out+=pt
        print('=====',p,who); print(out.split(b'\r\n\r\n')[0].decode('latin1')[:200] if who=='C' else '');
        if who=='S' and out.startswith(b'HTTP/1.0 200'): open('flag_%d.jpg'%p,'wb').write(out.split(b'\r\n\r\n',1)[1])
