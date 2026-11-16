exec(open('/Users/makoto.sugita/personal/METIS/.metis-state/work/22-solve.py').read().split("n=len(rows)")[0])
N=29
M0=[[1 if rows[y+1][x+1].isupper() else 0 for x in range(N)] for y in range(N)]  # 1=dark
print('\n'.join(''.join('##' if v else '  ' for v in r) for r in M0))
def fmt_try(M):
    # format bits positions
    bits1=[M[8][i] for i in (0,1,2,3,4,5,7,8)]+[M[i][8] for i in (7,5,4,3,2,1,0)]
    # read per spec: bits 14..0 ; first copy around top-left: (8,0..5),(8,7),(8,8),(7,8),(5..0,8)
    seq=[M[8][0],M[8][1],M[8][2],M[8][3],M[8][4],M[8][5],M[8][7],M[8][8],M[7][8],M[5][8],M[4][8],M[3][8],M[2][8],M[1][8],M[0][8]]
    v=0
    for b in seq: v=(v<<1)|b   # bit14 first
    return v
def bch_ok(v):
    best=None
    for ecl in range(4):
        for mask in range(8):
            d=(ecl<<3)|mask
            r=d<<10; g=0x537
            for i in range(14,9,-1):
                if r>>i&1: r^=g<<(i-10)
            code=((d<<10)|r)^0x5412
            dist=bin(code^v).count('1')
            if best is None or dist<best[0]: best=(dist,ecl,mask)
    return best
def transforms(M):
    T=[list(map(list,zip(*M)))]
    out=[M,T[0]]
    for base in (M,T[0]):
        out.append([r[::-1] for r in base]); out.append(base[::-1])
    return out
func=[[0]*N for _ in range(N)]
def rect(y0,x0,h,w):
    for y in range(y0,y0+h):
        for x in range(x0,x0+w):
            if 0<=y<N and 0<=x<N: func[y][x]=1
rect(0,0,9,9); rect(0,N-8,9,8); rect(N-8,0,8,9)
rect(6,0,1,N); rect(0,6,N,1); rect(20,20,5,5); func[N-8][8]=1
def decode(M,ecl,mask):
    maskf=[lambda y,x:(y+x)%2==0,lambda y,x:y%2==0,lambda y,x:x%3==0,lambda y,x:(y+x)%3==0,
           lambda y,x:(y//2+x//3)%2==0,lambda y,x:(y*x)%2+(y*x)%3==0,lambda y,x:((y*x)%2+(y*x)%3)%2==0,lambda y,x:((y+x)%2+(y*x)%3)%2==0][mask]
    bits=[];x=N-1;up=True
    while x>0:
        if x==6: x-=1
        ys=range(N-1,-1,-1) if up else range(N)
        for y in ys:
            for xx in (x,x-1):
                if not func[y][xx]:
                    b=M[y][xx]^(1 if maskf(y,xx) else 0); bits.append(b)
        up=not up; x-=2
    cw=[int(''.join(map(str,bits[i:i+8])),2) for i in range(0,len(bits)-7,8)][:70]
    return cw
# v3: L:1 block 55 data; M:1x44; Q:2x17; H:2x13
EC={1:(55,[55]),0:(44,[44]),3:(34,[17,17]),2:(26,[13,13])}  # fmt ecl bits: L=01,M=00,Q=11,H=10
def parse(cw,ecl):
    nd,blocks=EC[ecl]
    if len(blocks)==1: data=cw[:nd]
    else:
        # interleave
        b0=blocks[0]; data=cw[0:2*b0:2]+cw[1:2*b0:2]
    bs=''.join(f'{c:08b}' for c in data)
    mode=bs[:4]; 
    if mode=='0100':
        n=int(bs[4:12],2); return bytes(int(bs[12+8*i:20+8*i],2) for i in range(n))
    return ('mode',mode,bs[:60])
for ti,M in enumerate(transforms(M0)):
  for inv in (0,1):
    MM=[[v^inv for v in r] for r in M]
    v=fmt_try(MM); dist,ecl,mask=bch_ok(v)
    if dist==0 and ti==0 and inv==0:
        print('transform',ti,'inv',inv,'dist',dist,'ecl',ecl,'mask',mask)
        cw=decode(MM,ecl,mask); print(cw[:12]); print(parse(cw,ecl))
