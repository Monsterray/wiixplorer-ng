#!/usr/bin/env python3
"""Production GIF parser/LZW: truncation, palette, interlace and reload."""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
def stripped(p):return '\n'.join(l for l in (root/p).read_text().splitlines() if not l.startswith('#include'))
s=stripped('source/ImageOperations/GifImage.cpp');s=s[:s.index('void GifImage::Draw(')]
code=r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <memory>
#include <new>
#include <algorithm>
#include "Diagnostics/MemoryProbes.h"
using u8=uint8_t;using u16=uint16_t;using u32=uint32_t;using u64=uint64_t;
struct Timer{};
#define ALIGN(n) (((n)+3)&~3)
#define datasizeRGBA8(w,h) (ALIGN(w)*ALIGN(h)*4)
u32 coordsRGBA8(u32 x,u32 y,u32 w){return (y/4*(w/4)+x/4)*64+(y%4*4+x%4)*2;}
void *memalign(size_t,size_t n){return malloc(n);}void DCFlushRange(void*,size_t){}
const char*tr(const char*p){return p;}void ShowError(const char*){}
u16 le16(u16 n){return n;}u32 le32(u32 n){return n;}
struct mallinfo {size_t fordblks;};struct mallinfo mallinfo(){return {32*1024*1024};}
u32 MEM2_freesize(){return 32*1024*1024;}
'''+stripped('source/ImageOperations/GifImage.hpp')+s+r'''
std::vector<u8> codes(const std::vector<unsigned>&input){
 std::vector<u8>b;unsigned bits=3,next=6,previous=0,bit=0;
 for(unsigned code:input){for(unsigned i=0;i<bits;++i){if(bit/8==b.size())b.push_back(0);b[bit/8]|=((code>>i)&1)<<(bit%8);++bit;}
  if(code==4){bits=3;next=6;previous=0;}else if(code!=5){if(previous && next<4096){++next;if(next==(1u<<bits) && bits<12)++bits;}previous=1;}
 }return b;
}
void dictionaries(){
 GifLzwTables table;u8 output[8192]={};
 auto self=codes({4,0,6,7,5});assert(LZWDecoder(self.data(),self.size(),output,2,8,6,1,false,table));for(unsigned i=0;i<6;++i)assert(output[i]==0);
 std::vector<unsigned> stream={4};for(unsigned i=0;i<8192;++i)stream.push_back(i%4);stream.push_back(5);auto packed=codes(stream);
 assert(LZWDecoder(packed.data(),packed.size(),output,2,128,128,64,false,table));for(unsigned i=0;i<8192;++i)assert(output[i]==i%4);
 stream={};for(unsigned i=0;i<32;++i){stream.push_back(4);stream.push_back((i/4)%4);}stream.push_back(5);packed=codes(stream);
 assert(LZWDecoder(packed.data(),packed.size(),output,2,4,4,8,true,table));unsigned rows[]={0,4,2,6,1,3,5,7};for(unsigned i=0;i<8;++i)for(unsigned x=0;x<4;++x)assert(output[rows[i]*4+x]==i%4);
 for(unsigned n=0;n<packed.size();++n)assert(!LZWDecoder(packed.data(),n,output,2,4,4,8,true,table));
}
int main(){dictionaries();u8 tiny[1]={0};{GifImage g(tiny,1);assert(g.GetFrameCount()==0);}
 const u8 gif[]={71,73,70,56,57,97,1,0,1,0,128,0,0,0,0,0,255,255,255,44,0,0,0,0,1,0,1,0,0,2,2,68,1,0,59};
 GifImage good(gif,sizeof(gif));assert(good.GetFrameCount()==1);assert(good.GetFrameImage(0)[0]==255 && good.GetFrameImage(0)[1]==0);
 for(unsigned n=0;n<sizeof(gif);++n){good.LoadImage(gif,n);assert(good.GetFrameCount()==0);}
 auto b=std::vector<u8>(gif,gif+sizeof(gif));b[24]=0xff;b[25]=0xff;good.LoadImage(b.data(),b.size());assert(!good.GetFrameCount());
 b.assign(gif,gif+sizeof(gif));b[29]=0;good.LoadImage(b.data(),b.size());assert(!good.GetFrameCount());
 b.assign(gif,gif+sizeof(gif));b[30]=250;good.LoadImage(b.data(),b.size());assert(!good.GetFrameCount());
 // Two local colors replace the global palette; bit 0x80 is local-table presence.
 b.assign(gif,gif+sizeof(gif));b[28]=0x80;b.insert(b.begin()+29,{255,0,0,0,255,0});good.LoadImage(b.data(),b.size());assert(good.GetFrameCount()==1 && good.GetFrameImage(0)[1]==255);
 assert(!good.GetFrameImage(-1) && !good.GetFrameImage(1));
}
'''
with tempfile.TemporaryDirectory(prefix='wx-gif-') as t:
 p=Path(t);(p/'test.cpp').write_text(code)
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-g','-fsanitize=address,undefined',str(p/'test.cpp'),'-I'+str(root/'source'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('GIF: bounded header/block/palette/LZW reads, dictionary overlap/growth/full table, interlace, local palette, exact decode and failed reload cleanup passed')
