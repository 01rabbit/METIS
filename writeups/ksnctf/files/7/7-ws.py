import sys
c=[ch for ch in open(sys.argv[1],'rb').read().decode() if ch in ' \t\n']
p=0
def t():
    global p
    p+=1;return c[p-1]
def num():
    s=t();b=''
    while (ch:=t())!='\n': b+='01'[ch=='\t']
    v=int(b or '0',2);return -v if s=='\t' else v
def lab():
    b=''
    while (ch:=t())!='\n': b+=ch
    return b
prog=[];L={}
while p<len(c):
    a=t()
    if a==' ':
        b=t()
        if b==' ':prog.append(('push',num()))
        elif b=='\n':prog.append(({' ':'dup','\t':'swap','\n':'pop'}[t()],))
        else:prog.append(({'\t':'copy','\n':'slide'}[b],num()))
    elif a=='\n':
        k={'  ':'mark',' \t':'call',' \n':'jmp','\t ':'jz','\t\t':'jn','\t\n':'ret','\n\n':'end'}[t()+t()]
        if k in('ret','end'):prog.append((k,))
        else:
            l=lab()
            if k=='mark':L[l]=len(prog)
            else:prog.append((k,l))
    else:
        b=t()
        if b==' ':prog.append(({'  ':'add',' \t':'sub',' \n':'mul','\t ':'div','\t\t':'mod'}[t()+t()],))
        elif b=='\n':prog.append(({'  ':'outc',' \t':'outn','\t ':'inc','\t\t':'inn'}[t()+t()],))
        else:prog.append(({' ':'store','\t':'load'}[t()],))
st=[];h={};cs=[];pc=0;out=''
n=0
while pc<len(prog) and n<10**6:
    n+=1
    i=prog[pc];pc+=1;o=i[0]
    if o=='push':st.append(i[1])
    elif o=='dup':st.append(st[-1])
    elif o=='swap':st[-1],st[-2]=st[-2],st[-1]
    elif o=='pop':st.pop()
    elif o=='copy':st.append(st[-1-i[1]])
    elif o=='slide':
        x=st.pop();del st[len(st)-i[1]:];st.append(x)
    elif o in('add','sub','mul','div','mod'):
        b=st.pop();a=st.pop()
        st.append({'add':a+b,'sub':a-b,'mul':a*b,'div':a//b if b else 0,'mod':a%b if b else 0}[o])
    elif o=='store':v=st.pop();h[st.pop()]=v
    elif o=='load':st.append(h.get(st.pop(),0))
    elif o=='outc':out+=chr(st.pop())
    elif o=='outn':out+=str(st.pop())
    elif o=='call':cs.append(pc);pc=L[i[1]]
    elif o=='jmp':pc=L[i[1]]
    elif o=='jz':
        if st.pop()==0:pc=L[i[1]]
    elif o=='jn':
        if st.pop()<0:pc=L[i[1]]
    elif o=='ret':pc=cs.pop()
    elif o=='inn':h[st.pop()]=33355524
    elif o=='end':break
print(repr(out),len(prog))
print(L)
for k,i in enumerate(prog):print(k,i)
