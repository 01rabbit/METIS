"""Step 3: k-means on normalised glyph features; montage + first-tile labels."""
import numpy as np, sys
from PIL import Image
W='/Users/makoto.sugita/personal/METIS/.metis-state/work/'
K=int(sys.argv[1])
z=np.load(W+'34-feat.npz'); F=z['F']; bb=z['bb']
wd=(bb[:,3]-bb[:,2]).astype(np.float32)[:,None]/15
X=np.hstack([F,wd*3]); N=len(X)
rng=np.random.default_rng(2); sub=rng.choice(N,30000,replace=False)
C=[X[sub[0]]]
for _ in range(K-1):
    d=np.min([((X[sub]-c)**2).sum(1) for c in C],axis=0); C.append(X[sub[rng.choice(len(sub),p=d/d.sum())]])
C=np.array(C)
def asg(A): return np.stack([((A-c)**2).sum(1) for c in C],1).argmin(1)
for it in range(25):
    l=asg(X[sub])
    for k in range(K):
        if (l==k).any(): C[k]=X[sub][l==k].mean(0)
lab=np.concatenate([asg(X[i:i+20000]) for i in range(0,N,20000)])
np.save(W+'34-lab2.npy',lab); np.save(W+'34-C2.npy',C)
print(np.bincount(lab,minlength=K)); print(lab[:32].tolist())
rows=[]
for r in range(0,K,8):
    row=[(C[k][:308].reshape(22,14)*255).astype(np.uint8) if k<K else np.zeros((22,14),np.uint8) for k in range(r,r+8)]
    rows.append(np.hstack(row))
img=np.vstack(rows); Image.fromarray(img).resize((img.shape[1]*6,img.shape[0]*6),Image.NEAREST).save(W+'34-clusters2.png')
