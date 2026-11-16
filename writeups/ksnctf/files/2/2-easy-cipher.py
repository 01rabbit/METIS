import codecs,re,sys
h=re.sub(r'<[^>]+>','\n',open(sys.argv[1],encoding='utf-8').read())
m=re.search(r'EBG KVVV[^\n]*',h).group(0)
p=codecs.decode(m,'rot13');print(p)
w=re.search(r'FLAG\w+',p).group(0)
print(w[:4]+'_'+w[4:])
