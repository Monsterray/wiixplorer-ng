#!/usr/bin/env python3
"""Production movie container/JPEG code with real host libjpeg and sanitizers."""
from pathlib import Path
import os,subprocess,tempfile,shlex
root=Path(__file__).resolve().parents[1]
def strip(p):return '\n'.join(l for l in (root/p).read_text().splitlines() if not l.startswith('#include') or l in ('#include "jpeglib.h"','#include <setjmp.h>'))
code=r'''
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <string>
#include <vector>
#include <algorithm>
#include <cmath>
#include <climits>
#include <new>
#include <sys/stat.h>
#include "Diagnostics/MemoryProbes.h"
using u8=uint8_t;using u16=uint16_t;using u32=uint32_t;using u64=uint64_t;using s16=int16_t;using s32=int32_t;using s64=int64_t;
#define UNUSED __attribute__((unused))
size_t WxMemoryBudget(){return 32*1024*1024;}
'''+strip('source/VideoOperations/gcvid.h')+'\n'+strip('source/VideoOperations/gcvid.cpp')+r'''
int main(){
 FILE*f=fopen("sample.jpg","wb");assert(f);jpeg_compress_struct c={};jpeg_error_mgr e={};c.err=jpeg_std_error(&e);jpeg_create_compress(&c);jpeg_stdio_dest(&c,f);c.image_width=5;c.image_height=3;c.input_components=3;c.in_color_space=JCS_RGB;jpeg_set_defaults(&c);jpeg_start_compress(&c,TRUE);u8 white[15];memset(white,255,15);while(c.next_scanline<c.image_height){u8*p=white;jpeg_write_scanlines(&c,&p,1);}jpeg_finish_compress(&c);jpeg_destroy_compress(&c);fclose(f);
 VideoFile*v=openVideo("sample.jpg");assert(v && v->getWidth()==5 && v->getHeight()==3);VideoFrame frame;v->getCurrentFrame(frame);assert(frame.getPitch()==16 && frame.getData()[0]==255);closeVideo(v);
 f=fopen("sample.jpg","rb");fseek(f,0,SEEK_END);size_t n=ftell(f);rewind(f);std::vector<u8>b(n);assert(fread(b.data(),1,n,f)==n);fclose(f);
 for(size_t i=0;i<n;i+=17){decodeRealJpeg(b.data(),i,frame);assert(!frame.getData());}
 decodeRealJpeg(b.data(),n,frame);assert(frame.getData());auto original=frame.getData();assert(!frame.resize(-1,3) && frame.getData()==original);assert(!frame.resize(INT_MAX,3));
 f=fopen("bad","wb");assert(f);fwrite("THP\0",1,4,f);fclose(f);for(unsigned i=0;i<100;++i)assert(!openVideo("bad"));
 u8 packet[2]={0};assert(convertToRealJpeg(packet,packet,2)==0);
 remove("bad");remove("sample.jpg");
}
'''
with tempfile.TemporaryDirectory(prefix='wx-video-codec-') as t:
 p=Path(t);(p/'test.cpp').write_text(code)
 flags=shlex.split(subprocess.check_output([os.environ.get('PKG_CONFIG','pkg-config'),'--cflags','--libs','libjpeg'],text=True))
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-g','-fsanitize=address,undefined',str(p/'test.cpp'),'-I'+str(root/'source'),*flags,'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],cwd=p,check=True,timeout=30)
print('Video codec: real streaming JPEG, odd stride, truncation/errors, invalid dimensions and short containers passed')
