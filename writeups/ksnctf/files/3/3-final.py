import pickle,re,sys
V,o=pickle.load(open(sys.argv[1],'rb'))
p=V['ᒧうーｰｰｰー']
print(re.sub(r'\\u([0-9a-f]{4})',lambda m:chr(int(m.group(1),16)),p))
