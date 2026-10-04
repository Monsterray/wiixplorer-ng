/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "TransferBench.h"
#if WX_DEBUG_BUILD
#include "Memory/mem2.h"
#include "Memory/mem2alloc.hpp"
#include <gccore.h>
#include <ogc/cache.h>
#include <ogc/irq.h>
#include <ogc/lwp_watchdog.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <malloc.h>
#include <zlib.h>
#include <limits.h>

#if defined(GEKKO)
extern "C" void *__wrap_calloc(size_t, size_t);
extern "C" void *__wrap_realloc(void *, size_t);
static bool MemoryAllocatorChecks()
{
    // Outside timed kernels: exercise the real 32-bit pool and wrappers.
    void *backing = MEM2_alloc(32768);
    if (!backing) return false;
    CMEM2Alloc pool;
    pool.init(backing, (u8*)backing+32768);
    void *a = pool.allocate(20000), *b = pool.allocate(12000);
    bool okay = a && b && !pool.allocate(UINT_MAX);
    if (okay) {
        memset(b, 0x71, 12000);
        pool.release(a);
        void *moved = pool.reallocate(b, 16000);
        okay = moved == a;
        if (moved) {
            for (unsigned i=0;i<12000;++i) if (((u8*)moved)[i]!=0x71) okay=false;
            pool.release(moved);
        } else pool.release(b);
    }
    pool.clear();
    a = pool.allocate(32768-32);
    okay = okay && a && !pool.allocate(1) && !pool.reallocate(a, UINT_MAX);
    pool.release(a);
    okay = okay && pool.LargestFreeSize()==32768-32 && !__wrap_calloc(SIZE_MAX, 2);
    pool.cleanup(); MEM2_free(backing);
    a = MEM1_alloc(64);
    if (!a) return false;
    memset(a, 0x52, 64);
    void *grown = __wrap_realloc(a, UINT_MAX);
    if (grown) { free(grown); return false; }
    for (unsigned i=0;i<64;++i) if (((u8*)a)[i]!=0x52) okay=false;
    okay = !__wrap_realloc(a, 0) && okay;
    a = MEM2_alloc(64);
    if (!a) return false;
    okay = !__wrap_realloc(a, 0) && okay;
    printf("Memory allocator checks: %s\n", okay ? "passed" : "FAILED");
    fflush(stdout);
    return okay;
}
#endif

static const unsigned MemoryBlock=256*1024, HotBlock=8192, MemoryBytes=8*1024*1024;

// Volatile accesses preserve every hot-loop read/write; these are CPU kernels,
// not a claim that repeatedly accessing an 8 KiB buffer measures DRAM bandwidth.
static u32 ReadWords(const volatile u32 *p,unsigned words,unsigned loops)
{
    u32 sum=0;
    for(unsigned n=0;n<loops;++n) for(unsigned i=0;i<words;++i) sum+=p[i];
    return sum;
}
static void WriteWords(volatile u32 *p,unsigned words,unsigned loops)
{
    for(unsigned n=0;n<loops;++n) for(unsigned i=0;i<words;++i) p[i]=i^0x12345678;
}

static void MemorySync()
{
#if defined(GEKKO)
    __asm__ volatile("sync":::"memory");
#else
    __asm__ volatile("":::"memory");
#endif
}
static u8 *MemoryAlias(u8 *cached,bool uncached)
{
    if(!cached) return NULL;
#if defined(GEKKO)
    return uncached ? (u8*)MEM_K0_TO_K1(cached) : cached;
#else
    // Host coverage checks control flow/data verification, not cache behavior.
    (void)uncached;return cached;
#endif
}
static void CopyWords(volatile u32 *dst,const volatile u32 *src,unsigned words,unsigned loops)
{
    // No libc dcbz/prefetch assumptions on cache-inhibited aliases.
    for(unsigned n=0;n<loops;++n) for(unsigned i=0;i<words;++i) dst[i]=src[i];
}

static unsigned MemoryQueueLength()
{
#if defined(GEKKO)
    u32 hid2;
    __asm__ volatile("mfspr %0,920":"=r"(hid2));
    return (hid2>>24)&15; // DMAQL; official libogc 3.1.0 shifts by 4.
#else
    return LCQueueLength();
#endif
}
static bool MemoryDrain()
{
    u64 start=gettime();
    while(MemoryQueueLength()) {
        if(ticks_to_microsecs(gettime()-start)>100000) {
            LCFlushQueue();
            return false;
        }
    }
    MemorySync();
    return true;
}

// Official libogc 3.1.0 clears four upper address bits in LCLoad/StoreBlocks,
// dropping MEM2's bit 28. Keep it, as libogc2 does. Two queued 4 KiB transfers
// use a zero block-count encoding (=128 cache lines), then drain the queue.
static u32 MemoryDmaLower(u32 lc,bool load)
{
    // DMAL holds the cache tag address, not an offset within the 16 KiB bank.
    // Preserve 0xe0000000 to match the tags allocated by LCEnable.
    return (lc&~31u)|(load ? 0x12u : 0x02u);
}
static bool MemoryDma(u8 *lc,u8 *ram,bool load)
{
#if defined(GEKKO)
    for(unsigned offset=0;offset<HotBlock;offset+=4096) {
        u32 upper=(u32)(ram+offset)&0x1fffffe0u;
        u32 lower=MemoryDmaLower((u32)(lc+offset),load);
        __asm__ volatile("sync; mtspr 922,%0; mtspr 923,%1"::"r"(upper),"r"(lower):"memory");
    }
#else
    if(load) LCLoadData(lc,ram,HotBlock);else LCStoreData(ram,lc,HotBlock);
#endif
    return MemoryDrain();
}

struct LockedCacheState {
#if defined(GEKKO)
    u32 msr,hid2,batUpper,batLower;
    bool enable() {
        __asm__ volatile("mfmsr %0; mfspr %1,920; mfspr %2,542; mfspr %3,543"
                         : "=r"(msr),"=r"(hid2),"=r"(batUpper),"=r"(batLower));
        if((hid2&0x10000000u) || MemoryQueueLength()) return false;
        LCEnable();
        return true;
    }
    void disable() {
        if(!MemoryDrain()) LCFlushQueue();
        LCDisable();
        u32 level=IRQ_Disable();
        __asm__ volatile("sync; mtspr 543,%0; mtspr 542,%1; mtspr 920,%2; isync"
                         :: "r"(batLower),"r"(batUpper),"r"(hid2):"memory");
        // LCEnable sets MSR[ME]. Preserve the current interrupt state.
        u32 current;
        __asm__ volatile("mfmsr %0":"=r"(current));
        current=(current&~0x1000u)|(msr&0x1000u);
        __asm__ volatile("mtmsr %0; isync"::"r"(current):"memory");
        IRQ_Restore(level);
    }
#else
    bool enable(){LCEnable();return true;}
    void disable(){MemoryDrain();LCDisable();}
#endif
};

static bool MemoryCheckpoint(FILE *out)
{
    // fflush alone can leave FAT file length/directory metadata unpublished.
    // Persist diagnostic rows outside the measured interval before the next kernel.
    return fflush(out)==0 && fsync(fileno(out))==0;
}
static bool MemoryRow(FILE *out,const char *operation,const char *src,const char *dst,
                      unsigned block,unsigned repeat,u64 ticks,bool verified)
{
    return fprintf(out,"%s,%s,%s,%u,%u,%u,%llu,%u\n",operation,src,dst,block,repeat,
                   MemoryBytes,ticks_to_microsecs(ticks),verified)>0 && MemoryCheckpoint(out) && verified && ticks;
}

static bool MemoryAliasBench(FILE *out,u8 **buffers,const u32 *single)
{
    const char *names[]={"MEM1-K0","MEM1-K1","MEM2-K0","MEM2-K1"};
    // Source and destination allocations are distinct even within one bank.
    for(unsigned repeat=0;repeat<3;++repeat) for(unsigned src=0;src<4;++src)
        for(unsigned dst=0;dst<4;++dst) {
            u8 *cachedSrc=buffers[(src/2)*2],*cachedDst=buffers[(dst/2)*2+1];
            DCFlushRange(cachedSrc,MemoryBlock);DCFlushRange(cachedDst,MemoryBlock);
            u64 start=gettime();
            CopyWords((volatile u32*)MemoryAlias(cachedDst,dst&1),
                      (const volatile u32*)MemoryAlias(cachedSrc,src&1),
                      MemoryBlock/4,MemoryBytes/MemoryBlock);
            // Cached output publication is timed; uncached stores also drain.
            if(!(dst&1)) DCFlushRange(cachedDst,MemoryBlock);
            MemorySync();u64 elapsed=gettime()-start;
            // Verify through K0 only after K1 writes have completed.
            DCInvalidateRange(cachedDst,MemoryBlock);
            if(!MemoryRow(out,"copy32_alias",names[src],names[dst],MemoryBlock,repeat,
                          elapsed,crc32(0,cachedDst,MemoryBlock)==single[src/2])) return false;
        }
    const unsigned blocks[]={HotBlock,MemoryBlock};
    for(unsigned b=0;b<2;++b) for(unsigned region=0;region<4;++region)
        for(unsigned repeat=0;repeat<3;++repeat) {
            unsigned block=blocks[b],words=block/4,loops=MemoryBytes/block;
            u8 *cached=buffers[(region/2)*2+1],*alias=MemoryAlias(cached,region&1);
            WriteWords((volatile u32*)cached,words,1);DCFlushRange(cached,block);
            u32 expected=0;for(unsigned i=0;i<words;++i) expected+=i^0x12345678;
            // Warm the selected alias, checking visibility of the K0 pattern.
            if(ReadWords((const volatile u32*)alias,words,1)!=expected) return false;
            u64 start=gettime();
            u32 got=ReadWords((const volatile u32*)alias,words,loops);
            MemorySync();u64 elapsed=gettime()-start;
            if(!MemoryRow(out,b ? "read32_alias_stream" : "read32_alias_hot",names[region],
                          "CPU",block,repeat,elapsed,got==expected*loops)) return false;
            // Start writes from zero so unchanged output cannot pass verification.
            memset(cached,0,block);DCFlushRange(cached,block);
            start=gettime();WriteWords((volatile u32*)alias,words,loops);
            if(!(region&1)) DCFlushRange(cached,block);
            MemorySync();elapsed=gettime()-start;DCInvalidateRange(cached,block);
            bool verified=true;
            for(unsigned i=0;i<words;++i) if(((volatile u32*)cached)[i]!=(i^0x12345678)) verified=false;
            if(!MemoryRow(out,b ? "write32_alias_stream" : "write32_alias_hot","CPU",names[region],
                          block,repeat,elapsed,verified)) return false;
        }
    return true;
}

static u32 MemoryInfo(unsigned address)
{
#if defined(GEKKO)
    return *(volatile u32*)address; // IOS boot-info fields, read-only.
#else
    (void)address;return 0;
#endif
}

static u32 MemoryArenaBytes(u32 low,u32 high,u32 base,u32 physical)
{
    // IOS can leave MEM1's arena start unset. Such fields are not a usable
    // address range; never report a cached address as gigabytes of capacity.
    if(low<base || high<low || (u64)high>(u64)base+physical) return 0;
    return high-low;
}

void RunMemoryBenchmark(const char *directory)
{
    if (!directory || strlen(directory)>700 || strncmp(directory,"sd:/",4) ||
        strstr(directory,"..") || mkdir(directory,0700)!=0) return;
    char report[768];
    snprintf(report,sizeof(report),"%s/memory-benchmark.csv",directory);
    u32 mem1Free=mallinfo().fordblks,mem2Free=MEM2_freesize(),mem2Largest=MEM2_largestblock();
    u32 arena1=SYS_GetArena1Size(),arena2=SYS_GetArena2Size();
    u8 *buffers[]={ (u8*)MEM1_memalign(32,MemoryBlock),(u8*)MEM1_memalign(32,MemoryBlock),
                   (u8*)MEM2_alloc(MemoryBlock),(u8*)MEM2_alloc(MemoryBlock) };
    bool okay=true;
#if defined(GEKKO)
    okay=MemoryAllocatorChecks();
#endif
    for(unsigned i=0;i<4;++i) {
        if (!buffers[i] || ((size_t)buffers[i]&31)) okay=false;
#if defined(GEKKO)
        if (buffers[i] && ((u32)buffers[i]>>28)!=(i<2 ? 8u : 9u)) okay=false;
#endif
    }
    snprintf(report,sizeof(report),"%s/memory-capacity.csv",directory);
    FILE *meta=fopen(report,"wb");
    if(meta) {
        fprintf(meta,"bank,physical_bytes,ios_simulated_bytes,ios_arena_bytes,unallocated_arena_bytes,allocator_free_before,benchmark_allocated_bytes,source_address,destination_address,uncached_source_address,uncached_destination_address,allocator_largest_before\n");
        u32 lo1=MemoryInfo(0x8000310c),hi1=MemoryInfo(0x80003110);
        u32 lo2=MemoryInfo(0x80003124),hi2=MemoryInfo(0x80003128);
        fprintf(meta,"MEM1,%u,%u,%u,%u,%u,%u,%08x,%08x,%08x,%08x,\n",MemoryInfo(0x80003100),MemoryInfo(0x80003104),MemoryArenaBytes(lo1,hi1,0x80000000,MemoryInfo(0x80003100)),
                arena1,mem1Free,2*MemoryBlock,(u32)(size_t)buffers[0],(u32)(size_t)buffers[1],(u32)(size_t)MemoryAlias(buffers[0],true),(u32)(size_t)MemoryAlias(buffers[1],true));
        fprintf(meta,"MEM2,%u,%u,%u,%u,%u,%u,%08x,%08x,%08x,%08x,%u\n",MemoryInfo(0x80003118),MemoryInfo(0x8000311c),MemoryArenaBytes(lo2,hi2,0x90000000,MemoryInfo(0x80003118)),
                arena2,mem2Free,2*MemoryBlock,(u32)(size_t)buffers[2],(u32)(size_t)buffers[3],(u32)(size_t)MemoryAlias(buffers[2],true),(u32)(size_t)MemoryAlias(buffers[3],true),mem2Largest);
        fprintf(meta,"LC,16384,0,0,0,0,8192,e0000000,00000000,00000000,00000000,\n");
        if(fclose(meta)!=0) okay=false;
    } else okay=false;
    snprintf(report,sizeof(report),"%s/memory-benchmark.csv",directory);
    FILE *out=okay ? fopen(report,"wb") : NULL;
    const char *names[]={"MEM1","MEM2"};
    u32 seed=42,reference[2]={0,0};
    if(out) {
        if(fprintf(out,"operation,source,destination,block_bytes,repeat,bytes,ticks_us,verified\n")<=0 || !MemoryCheckpoint(out)) okay=false;
        // Keep partial measurements available after a native timeout.
        for(unsigned i=0;i<MemoryBlock;++i) {
            seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;
            buffers[0][i]=seed;
            buffers[2][i]=seed^0xa5; // Distinct regions catch DMA address aliasing.
        }
        const u32 single[]={(u32)crc32(0,buffers[0],MemoryBlock),(u32)crc32(0,buffers[2],MemoryBlock)};
        for(unsigned region=0;region<2;++region)
            for(unsigned n=0;n<MemoryBytes/MemoryBlock;++n)
                reference[region]=crc32(reference[region],buffers[region*2],MemoryBlock);
        void *(*volatile copy)(void*,const void*,size_t)=memcpy;
        printf("Memory benchmark: allocated, starting memcpy/CRC\n");fflush(stdout);
        for(unsigned repeat=0;okay && repeat<3;++repeat) {
            for(unsigned src=0;okay && src<2;++src) for(unsigned dst=0;okay && dst<2;++dst) {
                u64 start=gettime();
                for(unsigned n=0;n<MemoryBytes/MemoryBlock;++n)
                    copy(buffers[dst*2+1],buffers[src*2],MemoryBlock);
                DCFlushRange(buffers[dst*2+1],MemoryBlock);
                u64 elapsed=gettime()-start;
                bool verified=crc32(0,buffers[dst*2+1],MemoryBlock)==single[src];
                okay=MemoryRow(out,"memcpy",names[src],names[dst],MemoryBlock,repeat,elapsed,verified);
            }
            for(unsigned src=0;okay && src<2;++src) {
                u32 crc=crc32(0,NULL,0);
                u64 start=gettime();
                for(unsigned n=0;n<MemoryBytes/MemoryBlock;++n)
                    crc=crc32(crc,buffers[src*2],MemoryBlock);
                okay=MemoryRow(out,"crc32_cached",names[src],"CPU",MemoryBlock,repeat,gettime()-start,crc==reference[src]);
            }
        }
        // Hot CPU accesses use the same 8 KiB footprint for all three regions.
        printf("Memory benchmark: starting LC and hot CPU loops\n");fflush(stdout);
        fflush(out);
        LockedCacheState state;
        const bool enabled=okay && state.enable();
        okay=okay && enabled;
        u8 *lc=enabled ? (u8*)LCGetBase() : NULL;
        for(unsigned region=0;okay && region<3;++region) {
            u8 *p=region<2 ? buffers[region*2+1] : lc;
            const char *name=region<2 ? names[region] : "LC";
            WriteWords((volatile u32*)p,HotBlock/4,1);
            u32 sum=ReadWords((volatile u32*)p,HotBlock/4,1)*(MemoryBytes/HotBlock);
            for(unsigned repeat=0;okay && repeat<3;++repeat) {
                u64 start=gettime();
                u32 got=ReadWords((volatile u32*)p,HotBlock/4,MemoryBytes/HotBlock);
                okay=MemoryRow(out,"read32_hot",name,"CPU",HotBlock,repeat,gettime()-start,got==sum);
                start=gettime();
                WriteWords((volatile u32*)p,HotBlock/4,MemoryBytes/HotBlock);
                u64 elapsed=gettime()-start;
                bool verified=true;
                for(unsigned i=0;i<HotBlock/4;++i)
                    if(((volatile u32*)p)[i]!=(i^0x12345678)) verified=false;
                okay=okay && MemoryRow(out,"write32_hot","CPU",name,HotBlock,repeat,elapsed,verified);
            }
        }
        // Synchronous, queue-drained DMA: time enqueue+wait only, verify each
        // chunk outside the timer. Cache coherence work is also outside it.
        printf("Memory benchmark: starting DMA\n");fflush(stdout);
        fflush(out);
        for(unsigned region=0;okay && region<2;++region) {
            DCFlushRange(buffers[region*2],MemoryBlock);
            DCFlushRange(buffers[region*2+1],MemoryBlock);
            for(unsigned repeat=0;okay && repeat<3;++repeat) {
                u64 load=0,store=0;
                bool verified=true;
                for(unsigned n=0;n<MemoryBytes/HotBlock;++n) {
                    unsigned offset=(n*HotBlock)%MemoryBlock;
                    u8 *src=buffers[region*2]+offset,*dst=buffers[region*2+1]+offset;
                    u64 start=gettime();
                    bool loaded=MemoryDma(lc,src,true);
                    load+=gettime()-start;
                    if(!loaded || memcmp(lc,src,HotBlock)) { verified=false; break; }
                    DCInvalidateRange(dst,HotBlock);
                    start=gettime();
                    bool stored=MemoryDma(lc,dst,false);
                    store+=gettime()-start;
                    if(!stored || memcmp(dst,src,HotBlock)) { verified=false; break; }
                }
                okay=MemoryRow(out,"dma_load",names[region],"LC",HotBlock,repeat,load,verified) &&
                     MemoryRow(out,"dma_store","LC",names[region],HotBlock,repeat,store,verified);
            }
        }
        printf("Memory benchmark: restoring LC state\n");fflush(stdout);
        if(enabled) state.disable(); // Also restores BAT/HID2/MSR before normal app work.
        // Alias comparisons use the normal cache configuration, after LC restoration.
        if(okay) okay=MemoryAliasBench(out,buffers,single);
        if(fclose(out)!=0) okay=false;
    } else okay=false;
    printf("Memory benchmark: releasing buffers, verified=%u\n",okay);fflush(stdout);
    MEM1_free(buffers[0]);MEM1_free(buffers[1]);MEM2_free(buffers[2]);MEM2_free(buffers[3]);
    snprintf(report,sizeof(report),"%s/memory-complete",directory);
    out=fopen(report,"wb");
    if(out){fprintf(out,"%u",okay);fclose(out);}
}
#endif
