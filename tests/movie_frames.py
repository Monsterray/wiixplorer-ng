#!/usr/bin/env python3
"""Production movie publication: size changes, OOM and queue bounds."""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'source/VideoOperations/WiiMovie.cpp').read_text();a=s.index('void WiiMovie::DecodeNextFrame()');s=s[a:s.index('void WiiMovie::Draw()',a)]
code=r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <vector>
#include <climits>
#include "Diagnostics/MemoryProbes.h"
using u8=uint8_t;using u32=uint32_t;
#define FRAME_BUFFERS 8
#define ALIGN(x) (((x)+3)&~3)
struct CMutex{void lock(){}void unlock(){}};
size_t budget=32*1024*1024;size_t WxMemoryBudget(){return budget;}
bool fail=false;void*MEM2_alloc(size_t n){return fail?nullptr:malloc(n);}
void MEM2_free(void*p){free(p);}
struct VideoFrame{int w=4,h=4;u8 data[512]={};const u8*getData(){return data;}int getWidth(){return w;}int getHeight(){return h;}int getPitch(){return w*3;}};
struct VideoFile{void copyCurrentFrame(std::vector<u8>&){}void decodeVideoFrame(VideoFrame&,std::vector<u8>&){}};
u8*RGB8ToRGB565Stride(const u8*,u8*dst,u32 w,u32 h,u32){assert(dst);memset(dst,0,ALIGN(w)*ALIGN(h)*2);return dst;}
class WiiMovie{public:VideoFile*Video;bool Playing=true,ExitRequested=false,bDecoding=false,decodeFailed=false;std::vector<u8>EncodedFrame;CMutex readDecodeMutex,frameMutex;VideoFrame VideoF;int width=0,height=0,FrameBufCount=0;u32 FrameBytes=0;u8*FrameBuf[8]={};void DecodeNextFrame();void SetFullscreen(){} };
'''+s+r'''
int main(){VideoFile v;WiiMovie m;m.Video=&v;m.DecodeNextFrame();assert(m.FrameBufCount==1 && m.height==4);m.VideoF.h=8;m.DecodeNextFrame();assert(m.height==8 && m.FrameBufCount==1);for(auto p:m.FrameBuf)free(p);
 WiiMovie oom;oom.Video=&v;fail=true;oom.DecodeNextFrame();assert(oom.FrameBufCount==0 && !oom.Playing && oom.ExitRequested);fail=false;
 WiiMovie limited;limited.Video=&v;budget=1;limited.DecodeNextFrame();assert(limited.FrameBufCount==0 && limited.decodeFailed && limited.ExitRequested);budget=32*1024*1024;
 WiiMovie full;full.Video=&v;full.FrameBufCount=8;full.DecodeNextFrame();assert(full.FrameBufCount==8);
}
'''
code=code.replace('#include <cassert>','#include <cassert>\n#include <cstring>')
with tempfile.TemporaryDirectory(prefix='wx-movie-') as t:
 p=Path(t);(p/'test.cpp').write_text(code)
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-g','-fsanitize=address,undefined',str(p/'test.cpp'),'-I'+str(root/'source'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('Movie: height-only change, padded capacity, OOM fail-closed and full queue passed')
