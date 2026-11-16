from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES=True
d=bytearray(open('/Users/makoto.sugita/personal/METIS/.metis-state/work/21x/flag.jpg','rb').read())
# DQT table 0 corrupted bytes 0x19b0..0x19bb: neighbours are 2..5 -> fill with 3,4
for i in range(0x19b0,0x19bc): d[i]=4
d[6703:6709]=bytes([2,0x11,1,3,0x11,1])
open('/Users/makoto.sugita/personal/METIS/.metis-state/work/21x/flag-patched.jpg','wb').write(d)
im=Image.open('/Users/makoto.sugita/personal/METIS/.metis-state/work/21x/flag-patched.jpg').convert('L')
im.save('/Users/makoto.sugita/personal/METIS/.metis-state/work/21x/flag-patched.png'); print(im.size)
