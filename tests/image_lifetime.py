#!/usr/bin/env python3
"""Production image reload lifecycle with fake codecs, under sanitizers."""
from pathlib import Path
import os, subprocess, tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'source/GUI/gui_imagedata.cpp').read_text()
s='\n'.join(l for l in s.splitlines() if not l.startswith('#include'))
code=r'''
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include "Diagnostics/MemoryProbes.h"
using u8=uint8_t;
#define GX_TF_RGBA8 6
#define ALIGN32(x) (((x)+31)&~31)
void *memalign(size_t,size_t n){return malloc(n);}
void DCFlushRange(void*,int){}
struct gdImage {};using gdImagePtr=gdImage*;
gdImagePtr gdImageCreateFromPngPtr(int,void*){return new gdImage;}
#define CODEC(name) gdImagePtr name(int,void*){return nullptr;}
CODEC(gdImageCreateFromJpegPtr) CODEC(gdImageCreateFromTiffPtr) CODEC(gdImageCreateFromBmpPtr)
CODEC(gdImageCreateFromGifPtr) CODEC(gdImageCreateFromGdPtr) CODEC(gdImageCreateFromGd2Ptr) CODEC(gdImageCreateFromTgaPtr)
void gdImageDestroy(gdImagePtr p){delete p;}
u8 *GDImageToRGBA8(gdImagePtr*,int*w,int*h){*w=4;*h=4;return (u8*)malloc(64);}
struct GifImage{static int live;GifImage(const u8*,int){++live;}~GifImage(){--live;}int GetFrameCount(){return 2;}int GetWidth(){return 4;}int GetHeight(){return 4;}};int GifImage::live=0;
struct TplImage{TplImage(const u8*,int){}int GetWidth(int){return 4;}int GetHeight(int){return 4;}int GetFormat(int){return 6;}const u8*GetTextureBuffer(int){static u8 pixels[64]={};return pixels;}int GetTextureSize(int){return 64;}};
class GuiImageData{public:GuiImageData();GuiImageData(const u8*,int);~GuiImageData();void LoadImage(const u8*,int);void LoadTPL(const u8*,int);u8*data;GifImage*AnimGif;int width,height;u8 format;
#if WX_PROBE_LEVEL>0
size_t dataSize;
#endif
};
uint64_t liveBytes=0;
extern "C" void wx_memory_record(unsigned,uintptr_t p,uint64_t n,int a){if(!p)return;if(a)liveBytes+=n;else{assert(liveBytes>=n);liveBytes-=n;}}
'''+s+r'''
int main(){u8 gif[8]={'G','I','F'},png[8]={0x89,'P','N','G'},bad[8]={0x88},tpl[8]={0,0x20,0xAF,0x30};
 {GuiImageData d(gif,8);assert(GifImage::live==1);d.LoadImage(gif,8);assert(GifImage::live==1);
 d.LoadImage(png,8);assert(GifImage::live==0 && d.data && d.width==4);d.LoadImage(tpl,8);assert(d.data);d.LoadImage(bad,8);assert(!d.data && !d.AnimGif && !d.width && !d.height);}
 assert(GifImage::live==0 && liveBytes==0);
}
'''
with tempfile.TemporaryDirectory(prefix='wx-image-life-') as t:
 p=Path(t);(p/'test.cpp').write_text(code)
 for level in (0,1):
  subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-g','-fsanitize=address,undefined',f'-DWX_PROBE_LEVEL={level}','-DWX_PROBE_CPU=0','-DWX_PROBE_GPU=1','-I'+str(root/'source'),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
  subprocess.run([str(p/'test')],check=True)
print('Image reload: GIF replacement, failed decode reset and texture accounting passed')
