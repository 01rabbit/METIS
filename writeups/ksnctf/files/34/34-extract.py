"""Step 1: load all tiles -> per-cell glyph mask (dominant colour) + unknown mask (other-colour line pixels)."""
import numpy as np, os
from PIL import Image
D='/Users/makoto.sugita/personal/METIS/.metis-state/work/34-tiles/image/'
names=sorted(os.listdir(D)); print(len(names), names[-1])
BG=(138,97,170)
G=[];U=[]
for n in names:
    a=np.array(Image.open(D+n).convert('RGB')).astype(int)
    key=a[:,:,0]*65536+a[:,:,1]*256+a[:,:,2]
    cc,ct0=np.unique(key,return_counts=True); bg=cc[ct0.argmax()]
    for c in range(32):
        k=key[:,c*32:(c+1)*32]
        cs,ct=np.unique(k[k!=bg],return_counts=True)
        dom=cs[ct.argmax()] if len(cs) else bg
        G.append(k==dom); U.append((k!=bg)&(k!=dom))
G=np.array(G);U=np.array(U)
np.savez_compressed('/Users/makoto.sugita/personal/METIS/.metis-state/work/34-cells.npz',G=G,U=U,names=np.array(names))
print(G.shape, G.sum(axis=(1,2)).mean())
