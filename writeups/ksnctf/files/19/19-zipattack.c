/* Biham-Kocher style known-plaintext attack on ZipCrypto (traditional PKWARE encryption).
 * Usage: 19-zipattack <cipherhex> <plain12hex> <known_offset> <part> <nparts> [only_hi16]
 *   cipherhex : encrypted stream from stream byte 0 (12 header bytes + data), >= offset+12 bytes
 *   plain12hex: 12 contiguous known plaintext bytes located at stream position known_offset (>=12)
 * Prints "FOUND x y z" = key state at stream position 0 (right after password processing).
 * r = 0..11 indexes the known run; S_r = keys before processing stream byte off+r.
 * Stage 1: enumerate z_11[2..31] (2^22) and walk back to get z_i and msb(y_i)=b_i (i=2..11, exact).
 * Stage 2: pivot s_7 = y_6+L_7 (top byte b6) with top8(M*s_7+1)=b7 => 2^16 per candidate;
 *          forward chain y_8..y_11 finds L_8..L_11 (= lsb of x), which fixes x_8; walk back and check b_2..b_6.
 */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t u32; typedef uint8_t u8; typedef uint16_t u16;
#define M 0x08088405u
static u32 T[256]; static u8 T3inv[256]; static u32 MINV;
static u8 cbuf[4096], pk[12], kk[12]; static int OFF;
static inline u32 crc(u32 c,u8 b){return (c>>8)^T[(c^b)&255];}
static inline u32 crcinv(u32 c,u8 b){u8 i=T3inv[c>>24];return ((c^T[i])<<8)|(u8)(i^b);}
static inline u8 ks(u32 z){u32 t=(z|2)&0xffff;return ((t*(t^1))>>8)&255;}
#define CAP 48
static u8 lst[256][64][CAP]; static int cnt[256][64];
static u32 A2[4096]; static int a2start[257]; static u16 a2ord[4096];
static u32 ML[256]; static int mlstart[257]; static u8 mlord[256];
static u32 zl[12]; static u8 idxs[12]; static u8 bb[12];
static u8 Lv[12];
static long found=0;

static void report(u32 x,u32 y,u32 z,int pos){
  while(pos>0){
    u8 b=y>>24; u32 zp=crcinv(z,b); u8 k=ks(zp); u8 p=cbuf[pos-1]^k;
    u32 xp=crcinv(x,p); u32 yp=(y-1)*MINV-(x&255);
    x=xp;y=yp;z=zp;pos--;
    if(pos>=OFF && pos<OFF+12 && p!=pk[pos-OFF]) return;
  }
  printf("FOUND %08x %08x %08x\n",x,y,z); fflush(stdout); found++;
}
static void finish(u32 y8){
  u32 T8=T[(Lv[8]^pk[8])&255],T9=T[(Lv[9]^pk[9])&255],T10=T[(Lv[10]^pk[10])&255];
  u8 x8b1=Lv[9]^(T8&255);
  u8 x9b1=Lv[10]^(T9&255);
  u8 x8b2=x9b1^((T8>>8)&255);
  u8 x10b1=Lv[11]^(T10&255);
  u8 x9b2=x10b1^((T9>>8)&255);
  u8 x8b3=x9b2^((T8>>16)&255);
  u32 x=(u32)Lv[8]|((u32)x8b1<<8)|((u32)x8b2<<16)|((u32)x8b3<<24);
  u32 y=y8;
  for(int r=8;r>=3;r--){
    u32 xp=crcinv(x,pk[r-1]);
    u32 yp=(y-1)*MINV-(x&255);
    if((yp>>24)!=bb[r-1]) return;
    x=xp;y=yp;
  }
  report(x,y,zl[2],OFF+2);
}
static void fwd(int r,u32 y,u32 y8){
  if(r==12){finish(y8);return;}
  u32 Cc=M*y+1; u8 tc=Cc>>24; u8 b=bb[r];
  for(int dc=0;dc<2;dc++){
    u8 t=(u8)(b-tc-dc);
    for(int j=mlstart[t];j<mlstart[t+1];j++){
      u8 L=mlord[j]; u32 yn=Cc+ML[L];
      if((yn>>24)!=b) continue;
      Lv[r]=L; fwd(r+1,yn,r==8?yn:y8);
    }
  }
}
static void stage2(void){
  for(int i=2;i<=11;i++) bb[i]=idxs[i]^(zl[i-1]&255);
  u32 base=M*((u32)bb[6]<<24)+1; u8 b7=bb[7];
  for(u32 u1=0;u1<4096;u1++){
    u32 Kc=base+M*(u1<<12); u8 tK=Kc>>24;
    for(int dc=0;dc<2;dc++){
      u8 t=(u8)(b7-tK-dc);
      for(int j=a2start[t];j<a2start[t+1];j++){
        u32 y7=Kc+A2[a2ord[j]];
        if((y7>>24)!=b7) continue;
        fwd(8,y7,0);
      }
    }
  }
}
static void back(int i){
  if(i==0){stage2();return;}
  u32 zi=zl[i]; u8 idx=T3inv[zi>>24]; u32 d=(zi^T[idx])<<8;
  int v6=(d>>10)&63; u8 k=kk[i-1];
  for(int j=0;j<cnt[k][v6];j++){
    u32 w8=lst[k][v6][j];
    u32 zp=(d&0xfffffc00u)|(w8<<2);
    zl[i]=(zi&~3u)|(((zp>>8)&3)^(T[idx]&3));
    zl[i-1]=zp; idxs[i]=idx;
    back(i-1);
  }
}
static int hexv(char c){return c<='9'?c-'0':(c|32)-'a'+10;}
int main(int argc,char**argv){
  if(argc<6){fprintf(stderr,"usage\n");return 1;}
  for(int i=0;i<256;i++){u32 c=i;for(int j=0;j<8;j++)c=(c&1)?(c>>1)^0xEDB88320u:c>>1;T[i]=c;T3inv[c>>24]=i;}
  u32 inv=M;for(int i=0;i<5;i++)inv*=2-M*inv;MINV=inv;
  int n=strlen(argv[1])/2;for(int i=0;i<n;i++)cbuf[i]=hexv(argv[1][2*i])*16+hexv(argv[1][2*i+1]);
  for(int i=0;i<12;i++)pk[i]=hexv(argv[2][2*i])*16+hexv(argv[2][2*i+1]);
  OFF=atoi(argv[3]);int part=atoi(argv[4]),np=atoi(argv[5]);int only=argc>6?atoi(argv[6]):-1;
  for(int i=0;i<12;i++)kk[i]=cbuf[OFF+i]^pk[i];
  /* keystream tables: lst[k][bits10..15] = list of bits 2..9 */
  for(u32 w=0;w<(1u<<14);w++){u32 z=w<<2;u8 k=ks(z);int v=(z>>10)&63;
    if(cnt[k][v]>=CAP){fprintf(stderr,"cap\n");return 2;}lst[k][v][cnt[k][v]++]=(z>>2)&255;}
  /* bucket A2 by top byte of M*u2 */
  for(int u=0;u<4096;u++)A2[u]=M*(u32)u;
  {int c[257]={0};for(int u=0;u<4096;u++)c[(A2[u]>>24)+1]++;for(int i=0;i<256;i++)c[i+1]+=c[i];
   memcpy(a2start,c,sizeof c);int f[256];for(int i=0;i<256;i++)f[i]=c[i];
   for(int u=0;u<4096;u++)a2ord[f[A2[u]>>24]++]=u;}
  for(int l=0;l<256;l++)ML[l]=M*(u32)l;
  {int c[257]={0};for(int u=0;u<256;u++)c[(ML[u]>>24)+1]++;for(int i=0;i<256;i++)c[i+1]+=c[i];
   memcpy(mlstart,c,sizeof c);int f[256];for(int i=0;i<256;i++)f[i]=c[i];
   for(int u=0;u<256;u++)mlord[f[ML[u]>>24]++]=u;}
  long done=0;
  for(u32 hi=0;hi<65536;hi++){
    if((int)(hi%np)!=part)continue; if(only>=0&&(int)hi!=only)continue;
    for(int v6=0;v6<64;v6++){u8 k=kk[11];
      for(int j=0;j<cnt[k][v6];j++){
        u32 w8=lst[k][v6][j];
        zl[11]=(hi<<16)|((u32)v6<<10)|(w8<<2);
        back(11);
      }}
    if(++done%256==0){fprintf(stderr,"part %d: %ld hi16 done\n",part,done);}
  }
  fprintf(stderr,"part %d finished, found=%ld\n",part,found);
  return 0;
}
