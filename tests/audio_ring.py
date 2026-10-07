#!/usr/bin/env python3
"""Production audio ring: shrinking, empty ring and failed reallocation."""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
def stripped(p):return '\n'.join(l for l in (root/p).read_text().splitlines() if not l.startswith('#include'))
code=r'''
#include <vector>
#include <cstdint>
#include <cassert>
#include <cstdlib>
#include <climits>
#include <new>
#include "Diagnostics/MemoryProbes.h"
using u8=uint8_t;using u16=uint16_t;using u32=uint32_t;
#define ALIGN32(n) (((n)+31)&~31)
unsigned IRQ_Disable(){return 0;}void IRQ_Restore(unsigned){}void DCFlushRange(void*,unsigned){}
bool fail=false;void*memalign(size_t,size_t n){return fail?nullptr:malloc(n);}
'''+stripped('source/Tools/BufferCircle.hpp')+stripped('source/Tools/BufferCircle.cpp')+r'''
int main(){BufferCircle b;b.Resize(3);b.SetBufferBlockSize(64);assert(b.GetBuffer());b.LoadNext();b.LoadNext();b.Resize(1);assert(b.Which()<b.Size());b.LoadNext();b.Resize(0);b.LoadNext();assert(!b.GetBuffer());
 b.Resize(2);b.SetBufferBlockSize(64);u8*p=b.GetBuffer();fail=true;b.SetBufferBlockSize(128);assert(b.GetBuffer()==p);fail=false;b.SetBufferSize(0,-1);assert(b.GetBufferSize(0)<=64);
}
'''
with tempfile.TemporaryDirectory(prefix='wx-audio-ring-') as t:
 p=Path(t);(p/'test.cpp').write_text(code)
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-g','-fsanitize=address,undefined',str(p/'test.cpp'),'-I'+str(root/'source'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('Audio ring: shrink/current index, empty ring, OOM preservation and bounded payload passed')
