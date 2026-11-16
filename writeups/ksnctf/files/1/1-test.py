import re,sys
t=re.sub(r'<[^>]+>','\n',open(sys.argv[1],encoding='utf-8').read())
print(re.search(r'FLAG_\w+',t).group(0))
