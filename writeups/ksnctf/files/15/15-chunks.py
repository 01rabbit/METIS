import struct
d = open("/Users/makoto.sugita/personal/METIS/.metis-state/work/15-jewel.png","rb").read()
p = 8
while p < len(d):
    l, t = struct.unpack(">I4s", d[p:p+8])
    if t not in (b"IDAT",): print(t, l, d[p+8:p+8+min(l,120)])
    p += 12 + l
