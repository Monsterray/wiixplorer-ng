#!/usr/bin/env python3
"""Production ring/resampler decode checks including looping empty input."""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
def stripped(path):return '\n'.join(l for l in (root/path).read_text().splitlines() if not l.startswith('#include'))
def function(signature):
 s=(root/'source/SoundOperations/SoundDecoder.cpp').read_text();a=s.index(signature);b=s.index('{',a);n=1;end=b+1
 while n:n+=(s[end]=='{')-(s[end]=='}');end+=1
 return s[a:end]
code=r'''
#include <cassert>
#include <cstdint>
#include <climits>
#include <cstring>
#include <cstdlib>
#include <vector>
#include <new>
#include "Diagnostics/MemoryProbes.h"
using u8=uint8_t;using u16=uint16_t;using u32=uint32_t;using u64=uint64_t;using s16=int16_t;
#define ALIGN32(n) (((n)+31)&~31)
unsigned IRQ_Disable(){return 0;}void IRQ_Restore(unsigned){}void DCFlushRange(void*,unsigned){}
bool fail=false;void*memalign(size_t,size_t n){return fail?nullptr:malloc(n);}
struct {int SoundblockCount=3,SoundblockSize=4096;bool ResampleTo48kHz=true;} Settings;
const u32 FixedPointShift=15,FixedPointScale=1<<15;const u8 SOUND_RAW=0;
'''+stripped('source/Tools/BufferCircle.hpp')+stripped('source/Tools/BufferCircle.cpp')+r'''
class SoundDecoder { public:
 void *file_fd=(void*)1;BufferCircle SoundBuffer;u8 SoundType;u16 SoundBlocks,whichLoad;int SoundBlockSize,CurPos,SampleRate=22050;bool ResampleTo48kHz,Loop,EndOfFile,Decoding,ExitRequested;u8 *ResampleBuffer;u32 ResampleRatio;int reads=0,remaining=0;
 void Init();void EnableUpsample();void Upsample(s16*,s16*,u32,u32);void Decode();
 bool IsStereo(){return true;}bool Is16Bit(){return true;}int Tell(){return 0;}void Rewind(){}
 int Read(u8 *p,int n,int){++reads;if(!remaining)return 0;n=n<remaining?n:remaining;memset(p,0,n);remaining-=n;return n;}
 ~SoundDecoder(){free(ResampleBuffer);}
};
'''+''.join(function(sig) for sig in ('void SoundDecoder::Init()','void SoundDecoder::EnableUpsample(void)','void SoundDecoder::Upsample(','void SoundDecoder::Decode()'))+r'''
int main(){
 {SoundDecoder d;d.Init();d.Loop=true;d.Decode();assert(d.EndOfFile && !d.Decoding && d.reads==2);}
 {SoundDecoder d;d.Init();d.remaining=7;d.Decode();assert(!d.ExitRequested && d.SoundBuffer.GetBufferSize(0)<=4096);}
 {SoundDecoder d;d.Init();d.SampleRate=0;d.EnableUpsample();assert(d.ExitRequested && !d.ResampleBuffer);}
 {SoundDecoder d;d.Init();d.SampleRate=1;d.EnableUpsample();assert(d.ExitRequested && !d.ResampleBuffer);}
 {SoundDecoder d;d.Init();fail=true;d.EnableUpsample();assert(d.ExitRequested);fail=false;}
 Settings.SoundblockCount=-1;{SoundDecoder d;d.Init();assert(d.ExitRequested && d.EndOfFile && d.SoundBuffer.Size()==0);}
 Settings.SoundblockCount=128;Settings.SoundblockSize=65535;{SoundDecoder d;d.Init();assert(d.ExitRequested && d.SoundBuffer.Size()==0);}
}
'''
with tempfile.TemporaryDirectory(prefix='wx-audio-decode-') as t:
 p=Path(t);(p/'test.cpp').write_text(code)
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-g','-fsanitize=address,undefined',str(p/'test.cpp'),'-I'+str(root/'source'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=10)
print('Audio decode: bounded settings, resample rates/OOM/odd bytes and looping empty stream terminate safely')
