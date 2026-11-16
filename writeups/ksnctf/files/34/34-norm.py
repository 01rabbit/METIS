"""Step 2b: normalise cells: 2x2 opening removes 1px noise lines, bbox crop, resize to 14x22."""
import numpy as np
from PIL import Image
W='/Users/makoto.sugita/personal/METIS/.metis-state/work/'
z=np.load(W+'34-cells.npz'); G=z['G']
def erode(a):
    return a[:,:-1,:-1]&a[:,1:,:-1]&a[:,:-1,1:]&a[:,1:,1:]
def dilate(e):
    n=e.shape[0]; o=np.zeros((n,32,32),bool)
    o[:,:-1,:-1]|=e; o[:,1:,:-1]|=e; o[:,:-1,1:]|=e; o[:,1:,1:]|=e
    return o
op=np.concatenate([dilate(erode(G[i:i+20000])) for i in range(0,len(G),20000)])
F=np.zeros((len(G),22*14),np.float32); bb=np.zeros((len(G),4),int)
for i in range(len(G)):
    ys,xs=np.where(op[i])
    if len(ys)==0: continue
    y0,y1,x0,x1=ys.min(),ys.max()+1,xs.min(),xs.max()+1
    bb[i]=(y0,y1,x0,x1)
    im=Image.fromarray((op[i][y0:y1,x0:x1]*255).astype(np.uint8)).resize((14,22),Image.BILINEAR)
    F[i]=np.asarray(im,np.float32).ravel()/255
np.savez_compressed(W+'34-feat.npz',F=F,bb=bb)
h=bb[:,1]-bb[:,0]; w=bb[:,3]-bb[:,2]
print(np.percentile(h,[1,50,99]),np.percentile(w,[1,50,99]),(h==0).sum())
