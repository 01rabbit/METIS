import struct
d = open('/Users/makoto.sugita/personal/METIS/.metis-state/work/24x/rightsout.bin', 'rb').read()
key = struct.unpack('<8I', d[0x538:0x538 + 32])      # expected last-8 click sequence
c = struct.unpack('<33I', d[0x558:0x558 + 132])      # encrypted message
print(key); print(''.join(chr(c[i] ^ key[i % 8]) for i in range(33)))
