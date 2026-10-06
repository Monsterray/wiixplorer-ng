/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef WX_MEMORY_PROBES_H
#define WX_MEMORY_PROBES_H
#include "Probes.h"
#include <stddef.h>
enum WxMemoryOwner { WX_MEM_COPY, WX_MEM_ZIP_PACK, WX_MEM_ZIP_EXTRACT,
    WX_MEM_RAR_STORE, WX_MEM_SEVEN_SDK, WX_MEM_FTP_STACK, WX_MEM_FTP_CORE,
    WX_MEM_HOME, WX_MEM_OWNER_COUNT };
#if WX_PROBE_LEVEL > 0
#ifdef __cplusplus
extern "C" {
#endif
void wx_memory_record(unsigned owner, uintptr_t address, uint64_t bytes, int allocate);
void wx_memory_stack(unsigned owner, const void *address, size_t bytes);
void wx_memory_snapshot(const char *tag);
void wx_memory_flush(void);
#ifdef __cplusplus
}
#endif
#define WX_MEMORY_ALLOC(group,owner,p,n) do { if (WX_PROBE_##group) wx_memory_record(owner,(uintptr_t)(p),n,1); } while (0)
#define WX_MEMORY_FREE(group,owner,p,n) do { if (WX_PROBE_##group) wx_memory_record(owner,(uintptr_t)(p),n,0); } while (0)
#define WX_MEMORY_SNAPSHOT(tag) do { if (WX_PROBE_CPU && WX_PROBE_LEVEL>=2) wx_memory_snapshot(tag); } while (0)
#define WX_MEMORY_STACK(owner,p,n) do { if (WX_PROBE_THREADS && WX_PROBE_LEVEL>=2) wx_memory_stack(owner,p,n); } while (0)
#else
#define WX_MEMORY_ALLOC(group,owner,p,n) ((void)0)
#define WX_MEMORY_FREE(group,owner,p,n) ((void)0)
#define WX_MEMORY_SNAPSHOT(tag) ((void)0)
#define WX_MEMORY_STACK(owner,p,n) ((void)0)
#define wx_memory_flush() ((void)0)
#endif
#ifdef __cplusplus
#if WX_PROBE_LEVEL > 0
// Logical buffer lifetime only; never owns, dereferences or frees the pointer.
class WxMemoryBuffer {
    unsigned owner; uintptr_t address; uint64_t bytes;
public:
    WxMemoryBuffer(unsigned o,const void *p,uint64_t n):owner(o),address((uintptr_t)p),bytes(n) {
        if(o<WX_MEM_OWNER_COUNT) wx_memory_record(o,address,n,1);
    }
    ~WxMemoryBuffer() { if(owner<WX_MEM_OWNER_COUNT && address) wx_memory_record(owner,address,bytes,0); }
private:
    WxMemoryBuffer(const WxMemoryBuffer &);
    WxMemoryBuffer &operator=(const WxMemoryBuffer &);
};
#define WX_MEMORY_BUFFER(group,owner,p,n) WxMemoryBuffer wx_memory_buffer(WX_PROBE_##group ? owner : WX_MEM_OWNER_COUNT, WX_PROBE_##group ? p : NULL, WX_PROBE_##group ? n : 0)
class WxMemoryOperation {
    const char *end;
public:
    WxMemoryOperation(const char *begin,const char *finish):end(finish) {
        if(WX_PROBE_CPU && WX_PROBE_LEVEL>=2) wx_memory_snapshot(begin);
    }
    ~WxMemoryOperation() { if(WX_PROBE_CPU && WX_PROBE_LEVEL>=2) wx_memory_snapshot(end); }
};
#define WX_MEMORY_OPERATION(begin,end) WxMemoryOperation wx_memory_operation(WX_PROBE_CPU && WX_PROBE_LEVEL>=2 ? begin : NULL, WX_PROBE_CPU && WX_PROBE_LEVEL>=2 ? end : NULL)
#else
#define WX_MEMORY_BUFFER(group,owner,p,n) ((void)0)
#define WX_MEMORY_OPERATION(begin,end) ((void)0)
#endif
#endif
#endif
