"""Step 5: isolate red overlay pixels, deskew by PCA rotation of coordinates (no resampling), render big in strips."""
import numpy as np
from PIL import Image, ImageDraw
W='/Users/makoto.sugita/personal/METIS/.metis-state/work/'
a=np.array(Image.open(W+'34-flag.jpg').convert('RGB')).astype(int)
r,g,b=a[...,0],a[...,1],a[...,2]
m=(r>190)&(g<110)&(b<110)&(r-g>110)
ys,xs=np.where(m); print(len(ys))
P=np.c_[xs,ys].astype(float); c=P.mean(0); u,s,vt=np.linalg.svd(P-c,full_matrices=False)
ang=np.degrees(np.arctan2(vt[0][1],vt[0][0])); print('angle',ang)
th=np.arctan2(vt[0][1],vt[0][0]); R=np.array([[np.cos(th),np.sin(th)],[-np.sin(th),np.cos(th)]])
Q=(P-c)@R.T
if Q[:,0].min()>-1: pass
print(Q.min(0),Q.max(0))
S=8
x0,y0=Q.min(0)
w=int((Q[:,0].max()-x0)*S)+20; h=int((Q[:,1].max()-y0)*S)+20
im=Image.new('L',(w,h),255); d=ImageDraw.Draw(im)
for x,y in Q:
    X=(x-x0)*S+10;Y=(y-y0)*S+10; d.ellipse([X-3,Y-3,X+3,Y+3],fill=0)
n=3; sw=w//n+40
for i in range(n):
    im.crop((max(0,i*(w//n)-20),0,min(w,(i+1)*(w//n)+20),h)).save(W+f'34-text{i}.png')
print(w,h)
# glyph segmentation by x-gaps (rotated coords), report top/bottom per glyph
order=np.argsort(Q[:,0]); xs_=Q[order,0]
cuts=[0]+[i+1 for i in range(len(xs_)-1) if xs_[i+1]-xs_[i]>1.6]+[len(xs_)]
print('glyph(top,bottom,height,width) in rotated px')
for i in range(len(cuts)-1):
    seg=Q[order[cuts[i]:cuts[i+1]]]
    print(i,round(seg[:,1].min(),1),round(seg[:,1].max(),1),round(np.ptp(seg[:,1]),1),round(np.ptp(seg[:,0]),1))
