import re,sys
src=open(sys.argv[1],encoding='utf8').read()
a=src.index('<script>\n')+9
t=src[a:src.index('</script>',a)].strip()
# jjencode-style (Nyaruko variant): split at top-level commas
stm=[x.strip() for x in t.split(',')]
NM=re.compile(r'\([ᒧ〳]ᆞωᆞ\)\.([^+\[\]()=\-,]+)')
V={}
order=[]
for s in stm:
    m=re.match(r'\([ᒧ〳]ᆞωᆞ\)\.([^+\[\]()=\-,]+)\s*=(.*)$',s,re.S)
    if m: order.append((m.group(1),m.group(2)))
# first 10 numeric names (0..9) in order of appearance; next 4 string constants
for i,(n,_) in enumerate(order[:10]): V[n]=i
SQ=''
cur=10
def ev(e):
    e=e.strip()
    m=re.fullmatch(r'(.*?)\[\(ᆞωᆞᒪ\)(.*)\]',e,re.S)
    if m:
        base=ev(m.group(1)); r=m.group(2)
        mm=NM.search(r)
        idx=V[mm.group(1)] if mm else 0
        return base[idx]
    parts=re.split(r'\+(?![^()]*\))',e)
    out=''
    for p in parts:
        p=p.strip()
        mm=NM.fullmatch(p)
        if mm: v=V[mm.group(1)]
        elif p=='ｰ': v=''
        else: raise ValueError(p)
        out+=str(v)
    return out
# string constants
n10=order[10:]
names=[n for n,_ in n10]
V[names[0]]='true'; V[names[1]]='false'; V[names[2]]='[object Object]'; V[names[3]]='undefined'
SQ=None
for n,e in n10:
    if n in V and isinstance(V[n],str) and n in names[:4]: continue
    if n in ('ᒧうーーーｰ',):
        V[n]='/""ω""//\\\\ω\\\\/'; continue
    if re.match(r'\(ᆞωᆞᒪ\)|ᆞωᆞᒪ',e) : continue
    try: V[n]=ev(e)
    except Exception as ex: print('skip',n,e[:60],ex,file=sys.stderr)
for k,v in V.items():
    if isinstance(v,str) and len(v)<20: print(repr(k),repr(v),file=sys.stderr)
import pickle
pickle.dump((V,order),open(sys.argv[2],'wb'))
