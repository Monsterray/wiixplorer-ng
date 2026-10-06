/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "MemoryProbes.h"
#if WX_PROBE_LEVEL > 0
#include "Memory/mem2.h"
#include <ogc/irq.h>
#include <malloc.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>

// Requested bytes, not allocator usable sizes. No pointer registry or allocation.
struct Owner { uint64_t live, peak, allocations, releases, failures, largest, errors; };
static Owner owners[WX_MEM_OWNER_COUNT][3]; // MEM1, MEM2, failed/unknown
static size_t stackPeaks[WX_MEM_OWNER_COUNT][2];
struct Snapshot { char tag[24]; unsigned mem1Used,mem1Free,mem2Used,mem2Free,largest,integrity; };
static Snapshot snapshots[8];
static unsigned head,count,dropped,serial,flushed,window,written;
static bool outputFailed;
static const char *names[]={"copy_io","zip_pack_io","zip_extract_io","rar_stored_io",
    "seven_sdk","ftp_stack","ftp_core","home_overlay","gui_texture","directory_path"};

void wx_memory_record(unsigned owner,uintptr_t address,uint64_t bytes,int allocate)
{
    if(owner>=WX_MEM_OWNER_COUNT || (!allocate && !address)) return;
    unsigned bank=!address ? 2 : (((uintptr_t)address>>28)==9 ? 1 : 0);
    unsigned irq=IRQ_Disable();
    Owner &s=owners[owner][bank];
    if(allocate) {
        if(bytes>s.largest) s.largest=bytes;
        if(!address) ++s.failures;
        else if(bytes>UINT64_MAX-s.live) ++s.errors;
        else { s.live+=bytes; ++s.allocations; if(s.live>s.peak) s.peak=s.live; }
    } else if(bytes>s.live) ++s.errors;
    else { s.live-=bytes; ++s.releases; }
    ++serial;
    IRQ_Restore(irq);
}
void wx_memory_stack(unsigned owner,const void *address,size_t bytes)
{
    if(owner>=WX_MEM_OWNER_COUNT || !address) return;
    // Caller has joined the worker; scan only its owned, prefilled stack.
    const unsigned char *p=(const unsigned char*)address;
    size_t untouched=0;
    while(untouched<bytes && p[untouched]==0xa5) ++untouched;
    unsigned irq=IRQ_Disable();
    unsigned bank=((uintptr_t)address>>28)==9 ? 1 : 0;
    if(bytes-untouched>stackPeaks[owner][bank]) stackPeaks[owner][bank]=bytes-untouched;
    ++serial;
    IRQ_Restore(irq);
}
void wx_memory_snapshot(const char *tag)
{
#if WX_PROBE_CPU && WX_PROBE_LEVEL >= 2
    Snapshot s={};
    snprintf(s.tag,sizeof(s.tag),"%s",tag ? tag : "unknown");
    struct mallinfo info=mallinfo();
    s.mem1Used=info.uordblks; s.mem1Free=info.fordblks;
    s.mem2Free=MEM2_freesize(); s.mem2Used=MEM2_heapsize()-s.mem2Free;
    s.largest=MEM2_largestblock();
#if WX_PROBE_LEVEL >= 3
    s.integrity=!MEM2_check();
#endif
    unsigned irq=IRQ_Disable();
    if(count<8) { snapshots[(head+count)%8]=s; ++count; }
    else ++dropped;
    ++serial;
    IRQ_Restore(irq);
#else
    (void)tag;
#endif
}
void wx_memory_flush(void)
{
    // Main thread only, via existing probe flush. No writes without an event.
    // Reserve 10 KiB for the maximum bounded row batch within the 64 KiB cap.
    unsigned irq=IRQ_Disable(); bool pending=serial!=flushed; IRQ_Restore(irq);
    if(!pending || outputFailed || written>54*1024) return;
    FILE *f=fopen("sd:/apps/WiiXplorer/memory-probes.csv",window ? "a" : "w");
    if(!f) return;
    Owner copy[WX_MEM_OWNER_COUNT][3]; size_t stacks[WX_MEM_OWNER_COUNT][2];
    Snapshot events[8]; unsigned n,generation,lost;
    irq=IRQ_Disable();
    memcpy(copy,owners,sizeof(copy)); memcpy(stacks,stackPeaks,sizeof(stacks));
    n=count; generation=serial; lost=dropped;
    for(unsigned i=0;i<n;++i) events[i]=snapshots[(head+i)%8];
    IRQ_Restore(irq);
    int bytes=0;
    bool okay=true;
    if(!window) {
        int ret=fprintf(f,"kind,window,owner,bank,live_bytes,peak_bytes,allocations,releases,failures,max_request_bytes,accounting_errors,stack_peak_bytes,mem1_used,mem1_free,mem2_used,mem2_free,mem2_largest,integrity_errors,dropped_snapshots\n");
        if(ret<0) okay=false; else bytes+=ret;
    }
    if(!window && okay) {
        unsigned storage=sizeof(owners)+sizeof(stackPeaks)+sizeof(snapshots)+7*sizeof(unsigned)+sizeof(outputFailed);
        int ret=fprintf(f,"storage,%u,fixed_buffers,MEM1,%u,%u,,,,,,,,,,,,,\n",window,storage,storage);
        if(ret<0) okay=false; else bytes+=ret;
    }
    for(unsigned o=0;o<WX_MEM_OWNER_COUNT && okay;++o) for(unsigned b=0;b<3 && okay;++b) {
        const Owner &s=copy[o][b];
        size_t stack=b<2 ? stacks[o][b] : 0;
        if(!s.allocations && !s.failures && !s.errors && !stack) continue;
        int ret=fprintf(f,"owner,%u,%s,%s,%llu,%llu,%llu,%llu,%llu,%llu,%llu,%u,,,,,,,\n",window,names[o],
            b==0 ? "MEM1" : b==1 ? "MEM2" : "unknown",(unsigned long long)s.live,(unsigned long long)s.peak,(unsigned long long)s.allocations,(unsigned long long)s.releases,(unsigned long long)s.failures,(unsigned long long)s.largest,(unsigned long long)s.errors,(unsigned)stack);
        if(ret<0) okay=false; else bytes+=ret;
    }
    for(unsigned i=0;i<n && okay;++i) {
        const Snapshot &s=events[i];
        int ret=fprintf(f,"snapshot,%u,%s,,,,,,,,,,%u,%u,%u,%u,%u,%u,%u\n",window,s.tag,s.mem1Used,s.mem1Free,s.mem2Used,s.mem2Free,s.largest,s.integrity,lost);
        if(ret<0) okay=false; else bytes+=ret;
    }
    if(fclose(f)!=0) okay=false;
    if(okay) {
        irq=IRQ_Disable();head=(head+n)%8;count-=n;flushed=generation;IRQ_Restore(irq);
        ++window;written+=bytes;
    } else outputFailed=true; // Preserve counters; never append over a partial batch.
}
#endif
