/* SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once
#include <gctypes.h>
#include <stddef.h>
#include <stdint.h>
#include <malloc.h>
#include "mem2.h"
// Explicit operation snapshot, not a reservation. Leave half the currently
// allocator-free memory for concurrent owners; checked allocation is final.
inline size_t WxMemoryBudget()
{
    uint64_t bytes=((uint64_t)mallinfo().fordblks+MEM2_freesize())/2;
    return bytes>SIZE_MAX ? SIZE_MAX : (size_t)bytes;
}
