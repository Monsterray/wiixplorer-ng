#!/usr/bin/env python3
"""Check the production MEM2 reservation and upstream stop integration with host stubs."""
from pathlib import Path
import os
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]

def function(source, signature):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

source = (ROOT/'source/Memory/mem2.cpp').read_text()
code = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <algorithm>
#include <climits>
#include <cerrno>
using u32 = uint32_t;
void *arena = (void *)0x90100000;
void *SYS_GetArena2Lo() { return arena; }
void *SYS_GetArena2Hi() { return (void *)0x94000000; }
unsigned SYS_GetArena2Size() { return 0x03f00000; }
void SYS_SetArena2Lo(void *p) { arena = p; }
struct CMEM2Alloc {
 uintptr_t lo=0, hi=0, cursor=0;
 void *lastFree=nullptr;
 void init(void *b, void *e) { lo=(uintptr_t)b; hi=(uintptr_t)e; cursor=lo; }
 void *getEndAddress() { return (void *)hi; }
 void *allocate(unsigned n) {
  n=(n+31)&~31u; if(cursor+n>hi) return nullptr;
  void *p=(void *)cursor; cursor+=n; return p;
 }
 void release(void *p) { assert((uintptr_t)p>=lo && (uintptr_t)p<hi); lastFree=p; }
 void *reallocate(void *, unsigned) { return nullptr; }
 static unsigned usableSize(void *) { return 0; }
 unsigned FreeSize() { return hi-cursor; }
 void cleanup() { if(arena==(void *)hi) arena=(void *)lo; lo=hi=cursor=0; }
};
static const u32 HbcKeepStart=0x91800000, HbcKeepEnd=0x91801140;
static CMEM2Alloc g_mem2gp, g_mem2upper;
static void *originalArena2Lo, *heapEnd;
'''
for signature in ['static bool HeapSizeValid(', 'static CMEM2Alloc &HeapFor(', 'void MEM2_init(', 'void MEM2_cleanup(',
                  'void *MEM2_alloc(', 'void MEM2_free(', 'unsigned int MEM2_freesize(']:
    code += function(source, signature).replace("(u32)originalArena2Lo", "(u32)(uintptr_t)originalArena2Lo") + '\n'
code += r'''
int main() {
 MEM2_init(52);
 assert(g_mem2gp.lo==0x90200000 && g_mem2gp.hi==HbcKeepStart);
 assert(g_mem2upper.lo==HbcKeepEnd && g_mem2upper.hi==0x93300000);
 assert((uintptr_t)arena==0x93300000);
 MEM2_init(4);assert((uintptr_t)arena==0x93300000);
 assert(MEM2_freesize()==0x03100000-(HbcKeepEnd-HbcKeepStart));
 void *low=MEM2_alloc(0x01600000); assert(low==(void *)0x90200000);
 void *high=MEM2_alloc(1024); assert(high==(void *)HbcKeepEnd);
 MEM2_free(low); MEM2_free(high); MEM2_free(nullptr);
 assert(g_mem2gp.lastFree==low && g_mem2upper.lastFree==high);
 MEM2_cleanup(); assert(arena==(void *)0x90100000);
 // A smaller heap wholly below the record still works.
 MEM2_init(4); assert(!g_mem2upper.hi); assert(MEM2_alloc(32));
 arena=(void *)0x93800000; // Another owner extended the arena: do not reset it.
 MEM2_cleanup(); assert(arena==(void *)0x93800000);
 MEM2_cleanup(); assert(arena==(void *)0x93800000);
 // No wraparound, backwards reservation or persistent-record allocation.
 MEM2_init(UINT32_MAX); assert(!heapEnd && arena==(void*)0x93800000);
 arena=(void*)0x932ffff1;MEM2_init(52);assert(!heapEnd && arena==(void*)0x932ffff1);
 arena=(void*)0x90100000;MEM2_init(UINT32_MAX);assert(heapEnd==(void*)0x93300000);MEM2_cleanup();
 MEM2_init(0);assert(!heapEnd && arena==(void*)0x90100000);
}
'''
# Exercise the app's production wrapper around the new upstream stop API.
shutdown = r'''
#include <cassert>
#include <cstdio>
#define WX_DEBUG_BUILD 1
using s32=int;
static bool ready=true;
static int stops=0,logs=0,stop_result=0;
s32 hbc_agent_stop(){++stops;return stop_result;}
void hbc_netlog_close(){++logs;}
'''
shutdown += function((ROOT/'source/Diagnostics/HbcAgent.cpp').read_text(), 'void HbcAgentShutdown()')
shutdown += r'''
int main(){
 HbcAgentShutdown();assert(stops==1 && logs==1 && !ready);
 HbcAgentShutdown();assert(stops==1 && logs==1);
 ready=true;stop_result=-110;
 HbcAgentShutdown();assert(stops==2 && logs==2 && !ready);
}
'''
with tempfile.TemporaryDirectory(prefix='wiixplorer-agent-') as tmp:
    for name, body in [('reservation',code), ('shutdown',shutdown)]:
        path=Path(tmp)/(name+'.cpp'); path.write_text(body)
        out=Path(tmp)/name
        subprocess.run([os.environ.get('CXX','c++'), '-std=c++11', '-Wno-int-to-void-pointer-cast', '-fsanitize=address,undefined',
                        str(path), '-o', str(out)], check=True)
        subprocess.run([str(out)],check=True)
print('HBC agent: split heap reservation/routing and idempotent upstream stop wrapper passed')
