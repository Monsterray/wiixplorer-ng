#!/usr/bin/env python3
"""Exercise memory report/verification and LC lifetime with host cache/DMA shims."""
from pathlib import Path
import os,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'source/Diagnostics/MemoryBench.cpp').read_text()
source='\n'.join(l for l in source.splitlines() if not l.startswith('#include'))
harness=r'''
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cassert>
#include <chrono>
#include <sys/stat.h>
#include <unistd.h>
#include <cerrno>
#include <zlib.h>

using u8=unsigned char;using u32=unsigned int;using u64=unsigned long long;
#define WX_DEBUG_BUILD 1
struct Info{unsigned fordblks;};Info mallinfo(){return {1048576};}
bool lcEnabled=false,failAlloc=false,corrupt=false,stall=false,queued=false;unsigned allocations=0;
bool failSync=false;unsigned syncCalls=0,lcActivations=0;
int benchFsync(int fd){++syncCalls;if(failSync){errno=EIO;return -1;}return fsync(fd);}
#define fsync benchFsync
unsigned char lc[16384] __attribute__((aligned(32)));
u64 gettime(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
u64 ticks_to_microsecs(u64 t){return t/1000;}
void *alloc(unsigned n){if(failAlloc)return nullptr;void *p=nullptr;assert(posix_memalign(&p,32,n)==0);++allocations;return p;}
unsigned MEM2_freesize(){return 1048576;}unsigned SYS_GetArena1Size(){return 0;}unsigned SYS_GetArena2Size(){return 0;}
unsigned MEM2_largestblock(){return 524288;}
void *MEM1_memalign(unsigned,unsigned n){return alloc(n);}void *MEM2_alloc(unsigned n){return alloc(n);}
void release(void *p){if(p){--allocations;free(p);}}
void MEM1_free(void *p){release(p);}void MEM2_free(void *p){release(p);}
void LCEnable(){assert(!lcEnabled);++lcActivations;lcEnabled=true;memset(lc,0,sizeof(lc));}
void LCDisable(){assert(lcEnabled);lcEnabled=false;}
void *LCGetBase(){assert(lcEnabled);return lc;}
unsigned LCQueueLength(){return queued ? 1 : 0;}void LCFlushQueue(){queued=false;}
void LCLoadData(void *dst,void *src,unsigned n){assert(lcEnabled && dst==lc && n==8192);memcpy(dst,src,n);if(stall)queued=true;if(corrupt)lc[0]^=1;}
void LCStoreData(void *dst,void *src,unsigned n){assert(lcEnabled && src==lc && n==8192);memcpy(dst,src,n);}
void DCFlushRange(void*,unsigned){}void DCInvalidateRange(void*,unsigned){}
'''
harness+=source+r'''
bool exists(const char *p){struct stat s;return stat(p,&s)==0;}
void complete(const char *p,int value){FILE *f=fopen(p,"rb");assert(f && fgetc(f)==value);fclose(f);assert(!lcEnabled && allocations==0);}
int main(){
 assert(MemoryAlias(nullptr,true)==nullptr);
 assert(MemoryDmaLower(0xe0000000,true)==0xe0000012);
 assert(MemoryDmaLower(0xe0001000,true)==0xe0001012);
 assert(MemoryDmaLower(0xe0000000,false)==0xe0000002);
 assert(MemoryArenaBytes(0,0x81800000,0x80000000,25165824)==0);
 assert(MemoryArenaBytes(0x80004000,0x81800000,0x80000000,25165824)==25165824-0x4000);
 assert(MemoryArenaBytes(0x90000800,0x93500000,0x90000000,67108864)==0x3500000-0x800);
 assert(MemoryArenaBytes(0x90000800,0xffffffff,0x90000000,67108864)==0);
 assert(MemoryArenaBytes(0x81800000,0x80004000,0x80000000,25165824)==0);
 mkdir("sd:",0700);RunMemoryBenchmark("nand:/unsafe");assert(!exists("nand:/unsafe"));
 mkdir("sd:/owned",0700);RunMemoryBenchmark("sd:/owned");assert(!exists("sd:/owned/memory-complete"));
 RunMemoryBenchmark("sd:/bench");complete("sd:/bench/memory-complete",'1');
 assert(exists("sd:/bench/memory-capacity.csv"));
 FILE *f=fopen("sd:/bench/memory-benchmark.csv","rb");assert(f);char line[256];assert(fgets(line,sizeof(line),f));unsigned rows=0;
 while(fgets(line,sizeof(line),f)){char op[32],src[16],dst[16];unsigned block,repeat,bytes,verified;u64 us;
  assert(sscanf(line,"%31[^,],%15[^,],%15[^,],%u,%u,%u,%llu,%u",op,src,dst,&block,&repeat,&bytes,&us,&verified)==8);
  assert(verified && bytes==8388608 && us>0 && repeat<3);++rows;
 }fclose(f);assert(rows==144 && syncCalls==145);
 unsigned beforeSyncFailure=lcActivations;
 failSync=true;RunMemoryBenchmark("sd:/sync-fail");complete("sd:/sync-fail/memory-complete",'0');failSync=false;
 assert(lcActivations==beforeSyncFailure);
 // Real alias copy verification must reject an incorrect expected source CRC.
 u8 *testBuffers[]={ (u8*)alloc(MemoryBlock),(u8*)alloc(MemoryBlock),(u8*)alloc(MemoryBlock),(u8*)alloc(MemoryBlock) };
 for(auto p:testBuffers)memset(p,0,MemoryBlock);
 u32 wrong[]={0,0};f=tmpfile();assert(f && !MemoryAliasBench(f,testBuffers,wrong));fclose(f);
 for(auto p:testBuffers)release(p);assert(allocations==0);
 failAlloc=true;RunMemoryBenchmark("sd:/oom");complete("sd:/oom/memory-complete",'0');failAlloc=false;
 corrupt=true;RunMemoryBenchmark("sd:/corrupt");complete("sd:/corrupt/memory-complete",'0');corrupt=false;
 stall=true;RunMemoryBenchmark("sd:/timeout");complete("sd:/timeout/memory-complete",'0');assert(!queued);
}
'''
with tempfile.TemporaryDirectory(prefix='wx-memory-check-') as tmp:
    p=Path(tmp);(p/'test.cpp').write_text(harness)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-O2','-fsanitize=address,undefined',str(p/'test.cpp'),'-lz','-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],cwd=p,check=True,timeout=30)
print('Memory benchmark: 144 verified rows (cached/uncached alias matrix), allocation cleanup, private directory, DMA corruption rejection and LC teardown passed')
