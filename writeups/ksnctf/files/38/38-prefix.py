import sys, re
data = open(sys.argv[1], 'rb').read()
# OpenSSL -pass file: reads one line (BIO_gets) and C-string truncates at NUL
line = data[:8191].split(b'\n', 1)[0]
pw = line.split(b'\x00', 1)[0].split(b'\r', 1)[0]
print('canned size', len(data), 'pw len', len(pw), 'pw hex head', pw[:40].hex())
print('first 0x0a at', data.find(b'\n'), 'first 0x00 at', data.find(b'\x00'), 'first 0x0d at', data.find(b'\r'))
