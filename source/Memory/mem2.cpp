
#include "mem2.h"
#include "mem2alloc.hpp"

#include <malloc.h>
#include <string.h>
#include <ogc/system.h>
#include <algorithm>
#include <stdint.h>
#define HBC_NETLOG_LAYOUT_ONLY
#define HBC_AGENT_LAYOUT_ONLY
#include <hbc_netlog.h>
#include <hbc_agent.h>

#define MAX_MEM1_ARENA_LO	((void *) (0x81700000-size))
#define MEM2_PRIORITY_SIZE	30720	// 30KB

// Forbid the use of MEM2 through malloc
u32 MALLOC_MEM2 = 0;

// Leave persistent HBC log/crash records between the two allocation ranges.
static const u32 HbcKeepStart = HBC_NETLOG_KEEP_ADDR;
static const u32 HbcKeepEnd = (HBC_CRASH_ADDR + sizeof(hbc_crash_block) + 31) & ~31u;
static CMEM2Alloc g_mem2gp, g_mem2upper;
static void *originalArena2Lo, *heapEnd;
static CMEM2Alloc &HeapFor(const void *p)
{
    return (uintptr_t)p >= HbcKeepEnd ? g_mem2upper : g_mem2gp;
}

static bool g_bigGoesToMem2 = false;

extern "C"
{

extern __typeof(malloc) __real_malloc;
extern __typeof(calloc) __real_calloc;
extern __typeof(realloc) __real_realloc;
extern __typeof(memalign) __real_memalign;
extern __typeof(free) __real_free;
extern __typeof(malloc_usable_size) __real_malloc_usable_size;


void MEM2_takeBigOnes(bool b)
{
	g_bigGoesToMem2 = b;
}

void MEM2_init(unsigned int mem2Size)
{
	originalArena2Lo = SYS_GetArena2Lo();
    u32 begin = std::max(((u32)originalArena2Lo + 31) & ~31u, 0x90200000u);
    u32 end = std::min(begin + std::min(mem2Size * 0x100000u, SYS_GetArena2Size() & ~31u), 0x93300000u);
    if (begin < HbcKeepStart) g_mem2gp.init((void *)begin, (void *)std::min(end, HbcKeepStart));
    if (end > HbcKeepEnd) g_mem2upper.init((void *)std::max(begin, HbcKeepEnd), (void *)end);
    heapEnd = (void *)end;
    SYS_SetArena2Lo(heapEnd);
}

void MEM2_cleanup(void)
{
	bool ownsArena = SYS_GetArena2Lo() == heapEnd;
	if (g_mem2upper.getEndAddress()) g_mem2upper.cleanup();
    if (g_mem2gp.getEndAddress()) g_mem2gp.cleanup();
    if (ownsArena) SYS_SetArena2Lo(originalArena2Lo);
}

void *MEM2_alloc(unsigned int s)
{
	void *p = g_mem2gp.getEndAddress() ? g_mem2gp.allocate(s) : NULL;
    return p ? p : (g_mem2upper.getEndAddress() ? g_mem2upper.allocate(s) : NULL);
}

void MEM2_free(void *p)
{
	if (p) HeapFor(p).release(p);
}

void *MEM2_realloc(void *p, unsigned int s)
{
	if (!p) return MEM2_alloc(s);
    void *result = HeapFor(p).reallocate(p, s);
    if (result || !s) return result;
    result = MEM2_alloc(s);
    if (result) {
        memcpy(result, p, std::min(s, MEM2_usableSize(p)));
        MEM2_free(p);
    }
    return result;
}

unsigned int MEM2_usableSize(void *p)
{
	return CMEM2Alloc::usableSize(p);
}

unsigned int MEM2_freesize()
{
	return (g_mem2gp.getEndAddress() ? g_mem2gp.FreeSize() : 0) +
           (g_mem2upper.getEndAddress() ? g_mem2upper.FreeSize() : 0);
}

void *MEM1_alloc(unsigned int s)
{
	return __real_malloc(s);
}

void *MEM1_memalign(unsigned int a, unsigned int s)
{
	return __real_memalign(a, s);
}

void MEM1_free(void *p)
{
	__real_free(p);
}

void *MEM1_realloc(void *p, unsigned int s)
{
	return __real_realloc(p, s);
}

void *__wrap_malloc(size_t size)
{
	void *p;
	if ((SYS_GetArena1Lo() > MAX_MEM1_ARENA_LO) || (g_bigGoesToMem2 && size > MEM2_PRIORITY_SIZE))
	{
		p = MEM2_alloc(size);
		if (p != 0) {
			return p;
		}
		return __real_malloc(size);
	}
	p = __real_malloc(size);
	if (p != 0) {
		return p;
	}
	return MEM2_alloc(size);
}

void *__wrap_calloc(size_t n, size_t size)
{
	void *p;
	if ((SYS_GetArena1Lo() > MAX_MEM1_ARENA_LO) || (g_bigGoesToMem2 && size > MEM2_PRIORITY_SIZE))
	{
		p = MEM2_alloc(n * size);
		if (p != 0)
		{
			memset(p, 0, n * size);
			return p;
		}
		return __real_calloc(n, size);
	}
	p = __real_calloc(n, size);
	if (p != 0) {
		return p;
	}
	p = MEM2_alloc(n * size);
	if (p != 0) {
		memset(p, 0, n * size);
	}
	return p;
}

void *__wrap_memalign(size_t a, size_t size)
{
	void *p;
	if ((SYS_GetArena1Lo() > MAX_MEM1_ARENA_LO) || (g_bigGoesToMem2 && size > MEM2_PRIORITY_SIZE))
	{
		if (a == 32)
		{
			p = MEM2_alloc(size);
			if (p != 0) {
				return p;
			}
		}
		return __real_memalign(a, size);
	}
	p = __real_memalign(a, size);
	if (p != 0 || a != 32) {
		return p;
	}

	return MEM2_alloc(size);
}

void __wrap_free(void *p)
{
	if(!p)
		return;

	if (((u32)p & 0x10000000) != 0)
	{
		MEM2_free(p);
	}
	else
	{
		__real_free(p);
	}
}

void *__wrap_realloc(void *p, size_t size)
{
	void *n;
	// ptr from mem2
	if (((u32)p & 0x10000000) != 0 || (p == 0 && g_bigGoesToMem2 && size > MEM2_PRIORITY_SIZE))
	{
		n = MEM2_realloc(p, size);
		if (n != 0) {
			return n;
		}
		n = __real_malloc(size);
		if (n == 0) {
			return 0;
		}
		if (p != 0)
		{
			memcpy(n, p, MEM2_usableSize(p) < size ? MEM2_usableSize(p) : size);
			MEM2_free(p);
		}
		return n;
	}
	// ptr from malloc
	n = __real_realloc(p, size);
	if (n != 0) {
		return n;
	}
	n = MEM2_alloc(size);
	if (n == 0) {
		return 0;
	}
	if (p != 0)
	{
		memcpy(n, p, __real_malloc_usable_size(p) < size ? __real_malloc_usable_size(p) : size);
		__real_free(p);
	}
	return n;
}

size_t __wrap_malloc_usable_size(void *p)
{
	if (((u32)p & 0x10000000) != 0)
		return CMEM2Alloc::usableSize(p);
	return __real_malloc_usable_size(p);
}

} ///extern "C"

#if WX_PROBE_CPU && WX_PROBE_LEVEL >= 3
bool MEM2_check() { return (!g_mem2gp.getEndAddress() || g_mem2gp.CheckIntegrity()) &&
           (!g_mem2upper.getEndAddress() || g_mem2upper.CheckIntegrity()); }
#endif
