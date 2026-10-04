#!/usr/bin/env python3
"""ASan/UBSan checks of the production MEM2 pool and allocation wrappers."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def function(signature):
    source = (ROOT/'source/Memory/mem2.cpp').read_text()
    start = source.index(signature)
    end = source.index('{', start)+1
    depth = 1
    while depth:
        depth += (source[end]=='{')-(source[end]=='}')
        end += 1
    return source[start:end]

pool = r'''
#include "Memory/mem2alloc.hpp"
#include <cassert>
#include <cstring>
#include <climits>
#include <random>
#include <vector>
#include <cstdint>
alignas(32) static unsigned char arena[32768];
void *SYS_GetArena2Lo(){return nullptr;}
void *SYS_GetArena2Hi(){return nullptr;}
void SYS_SetArena2Lo(void*){}
int main(){
 CMEM2Alloc a; assert(!a.allocate(32)); assert(a.FreeSize()==0);
 a.init(arena,arena+sizeof(arena));
 assert(a.FreeSize()==sizeof(arena)-32 && a.LargestFreeSize()==sizeof(arena)-32);
 // An exact fit uses the last payload slot, and overflow never forms a pointer.
 void *p=a.allocate(sizeof(arena)-32); assert(p && !a.allocate(1));
 assert(a.CheckIntegrity() && !a.allocate(UINT_MAX));
 assert(a.FreeSize()==0 && a.LargestFreeSize()==0);
 memset(p,0x52,sizeof(arena)-32);assert(!a.reallocate(p,UINT_MAX));
 assert(((unsigned char*)p)[100]==0x52);a.release(p);
 assert(a.FreeSize()==sizeof(arena)-32);
 a.clear();for(auto byte:arena)assert(byte==0);
 // Shrink, coalesce its free successor, and grow without moving the live data.
 p=a.allocate(256);void *q=a.allocate(256),*r=a.allocate(256);
 memset(p,0x63,256);a.release(q);assert(a.reallocate(p,64)==p);
 assert(a.FreeSize()>a.LargestFreeSize());
 assert(a.reallocate(p,512)==p && ((unsigned char*)p)[0]==0x63);
 a.release(r);assert(a.CheckIntegrity());assert(!a.reallocate(p,0));
 assert(a.FreeSize()==sizeof(arena)-32);
 // A tail object can move into an earlier free block when there is no tail room.
 a.clear();p=a.allocate(20000);q=a.allocate(12000);assert(p && q);
 memset(q,0x71,12000);a.release(p);r=a.reallocate(q,16000);
 assert(r==p);for(unsigned i=0;i<12000;++i)assert(((unsigned char*)r)[i]==0x71);
 a.release(r);assert(a.CheckIntegrity());
 // Deterministic mixed lifetimes expose broken split/coalesce/realloc links.
 std::mt19937 random(42);
 struct Live{void *p;unsigned size;unsigned char value;};std::vector<Live> live;
 for(unsigned step=0;step<10000;++step){
  if(live.empty() || random()%3==0){
   unsigned size=1+random()%2048;void *b=a.allocate(size);
   if(b){unsigned char v=1+random()%250;memset(b,v,size);live.push_back({b,size,v});}
  }else{
   unsigned pos=random()%live.size();Live &b=live[pos];
   for(unsigned i=0;i<b.size;++i)assert(((unsigned char*)b.p)[i]==b.value);
   if(random()%2){
    unsigned size=1+random()%4096;void *n=a.reallocate(b.p,size);
    if(n){for(unsigned i=0;i<(size<b.size?size:b.size);++i)assert(((unsigned char*)n)[i]==b.value);
     memset(n,b.value,size);b.p=n;b.size=size;}
   }else{a.release(b.p);live.erase(live.begin()+pos);}
  }
  assert(a.CheckIntegrity());
 }
 for(auto b:live)a.release(b.p);assert(a.CheckIntegrity());
 assert(a.FreeSize()==sizeof(arena)-32);a.cleanup();
}
'''
wrappers = r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <climits>
#include <cerrno>
using u32=uintptr_t;
static bool g_bigGoesToMem2=false;
#define MEM2_PRIORITY_SIZE 30720
void *SYS_GetArena1Lo(){return (void*)0x80004000;}
unsigned realCalls=0,mem2Calls=0,freeCalls=0;bool failReal=false;
void *__real_calloc(size_t n,size_t s){++realCalls;return failReal?nullptr:calloc(n,s);}
void *MEM2_alloc(unsigned n){++mem2Calls;return malloc(n?n:1);}
void *__real_malloc(size_t){++realCalls;return nullptr;}
void *__real_memalign(size_t,size_t){++realCalls;return nullptr;}
void *__real_realloc(void*,size_t s){assert(s);++realCalls;return nullptr;}
void *MEM2_realloc(void*,unsigned s){assert(s);++mem2Calls;return nullptr;}
unsigned MEM2_usableSize(void*){assert(false);return 0;}
size_t __real_malloc_usable_size(void*){assert(false);return 0;}
void __real_free(void *p){assert(p==(void*)0x80004020 || !p);if(p)++freeCalls;}
void MEM2_free(void *p){assert(p==(void*)0x90200020);++freeCalls;}
'''
for signature in ['static bool HeapSizeValid(', 'static bool PreferMem2(', 'void *__wrap_malloc(',
                  'void *__wrap_calloc(', 'void *__wrap_memalign(', 'void __wrap_free(', 'void *__wrap_realloc(']:
    wrappers += function(signature)+'\n'
wrappers += r'''
int main(){
 errno=0;assert(!__wrap_calloc(SIZE_MAX,2));assert(errno==ENOMEM);
 assert(!realCalls && !mem2Calls);
 g_bigGoesToMem2=true;void *p=__wrap_calloc(1024,32);assert(p && mem2Calls==1 && !realCalls);
 for(unsigned i=0;i<32768;++i)assert(((unsigned char*)p)[i]==0);free(p);
 g_bigGoesToMem2=false;failReal=true;
 p=__wrap_calloc(3,7);assert(p && realCalls==1 && mem2Calls==2);free(p);
 assert(!__wrap_realloc((void*)0x80004020,0));assert(freeCalls==1);
 assert(!__wrap_realloc((void*)0x90200020,0));assert(freeCalls==2);
 assert(!__wrap_realloc(nullptr,0));assert(freeCalls==2);
 assert(!__wrap_realloc((void*)0x80004020,UINT_MAX));assert(freeCalls==2);
 unsigned before=realCalls+mem2Calls;
 assert(!__wrap_realloc((void*)0x80004020,INT_MAX));
 assert(!__wrap_calloc(INT_MAX,1));assert(realCalls+mem2Calls==before);
 assert(!__wrap_malloc(INT_MAX));assert(!__wrap_memalign(32,INT_MAX));
 assert(realCalls+mem2Calls==before && freeCalls==2);
 assert(HeapSizeValid(INT_MAX-32) && !HeapSizeValid(INT_MAX-31));
 assert(PreferMem2(SIZE_MAX));assert(!PreferMem2(32));
}
'''
split = r'''
#include "Memory/mem2alloc.hpp"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <climits>
#include <cerrno>
#include <algorithm>
void *SYS_GetArena2Lo(){return nullptr;}
void *SYS_GetArena2Hi(){return nullptr;}
void SYS_SetArena2Lo(void*){}
alignas(32) static unsigned char low[1024],high[2048];
static uintptr_t HbcKeepEnd=(uintptr_t)high;
static CMEM2Alloc g_mem2gp,g_mem2upper;
extern unsigned int MEM2_usableSize(void*);
extern void MEM2_free(void*);
'''
for signature in ['static bool HeapSizeValid(', 'static CMEM2Alloc &HeapFor(',
                  'void *MEM2_alloc(', 'void MEM2_free(', 'unsigned int MEM2_usableSize(', 'void *MEM2_realloc(']:
    split += function(signature)+'\n'
split += r'''
int main(){
 // Arrays need a stable address ordering for the production split dispatch.
 unsigned char *first=low,*last=high;
 if((uintptr_t)first>(uintptr_t)last){first=high;last=low;}
 HbcKeepEnd=(uintptr_t)last;
 g_mem2gp.init(first,first+1024);g_mem2upper.init(last,last+1024);
 void *p=MEM2_alloc(512),*held=MEM2_alloc(448);assert(p && held);
 memset(p,0x43,512);void *moved=MEM2_realloc(p,768);
 assert(moved && (uintptr_t)moved>=HbcKeepEnd);
 for(unsigned i=0;i<512;++i)assert(((unsigned char*)moved)[i]==0x43);
 assert(!MEM2_realloc(moved,1024));
 for(unsigned i=0;i<512;++i)assert(((unsigned char*)moved)[i]==0x43);
 assert(!MEM2_realloc(moved,0));MEM2_free(held);
 assert(g_mem2gp.CheckIntegrity() && g_mem2upper.CheckIntegrity());
 assert(g_mem2gp.LargestFreeSize()==992 && g_mem2upper.LargestFreeSize()==992);
 g_mem2gp.cleanup();g_mem2upper.cleanup();
}
'''
# Failed realloc must not copy/free: MEM2 allocation returns NULL in this case.
wrappers=wrappers.replace('++mem2Calls;return malloc(n?n:1);','++mem2Calls;return n==UINT_MAX?nullptr:malloc(n?n:1);')
with tempfile.TemporaryDirectory(prefix='wx-allocator-') as tmp:
    p=Path(tmp);(p/'ogc').mkdir()
    (p/'ogc/mutex.h').write_text('typedef int mutex_t;\ninline int LWP_MutexInit(int*p,int){*p=1;return 0;}\ninline int LWP_MutexDestroy(int){return 0;}\ninline int LWP_MutexLock(int){return 0;}\ninline int LWP_MutexUnlock(int){return 0;}\n')
    (p/'ogc/system.h').write_text('void *SYS_GetArena2Lo();\nvoid *SYS_GetArena2Hi();\nvoid SYS_SetArena2Lo(void*);\n')
    for name,code in [('pool',pool),('wrappers',wrappers),('split',split)]:
        cpp=p/(name+'.cpp');cpp.write_text(code)
        inputs=[str(cpp)]
        if name in ('pool','split'):inputs += [str(ROOT/'source/Memory/mem2alloc.cpp')]
        subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-O1','-g','-fsanitize=address,undefined',
                        '-DWX_PROBE_CPU=1','-DWX_PROBE_LEVEL=3','-I'+str(p),'-I'+str(ROOT/'source'),
                        *inputs,'-o',str(p/name)],check=True)
        subprocess.run([str(p/name)],check=True,timeout=30)
print('Memory allocator: exact fit, SDK overflow guard, calloc routing, zero realloc, cross-pool/failure preservation and 10,000 mixed lifetimes passed')
