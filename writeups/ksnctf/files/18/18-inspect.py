import zipfile, sys, hashlib
p = sys.argv[1]
data = open(p, 'rb').read()
print('size', len(data), 'sha256', hashlib.sha256(data).hexdigest())
print('head', data[:16].hex())
z = zipfile.ZipFile(p)
for i in z.infolist():
    print(i.filename, i.file_size, i.compress_size, i.compress_type, i.date_time, hex(i.external_attr), i.comment, i.extra[:32])
print('zip comment', z.comment)
