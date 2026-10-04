# Memory optimization plan

Status: proposed implementation sequence, based on the v0.1.6 source audit
and the physical-Wii measurements in [MEMORY.md](MEMORY.md). This document
changes no runtime allocation, buffer size, cache policy or library.

Correctness and data safety come first, followed by bounded resources,
compatibility and measured performance. Keep changes confined to individual
owners and existing helpers; no allocator replacement or broad UI refactor.

## What the project actually does

* [Application.cpp](source/Controls/Application.cpp) requests a 52 MiB MEM2
  pool. [mem2.cpp](source/Memory/mem2.cpp) clamps its range between the IOS
  reload boundary and `0x93300000`, respecting the current arena and excluding
  the HBC retained log/crash region. Physical 64 MiB is not all application RAM.
* Wrapped allocations generally try MEM1 first, then MEM2. The optional
  greater-than-30-KiB MEM2 preference is off; no production caller enables
  `MEM2_takeBigOnes`. Allocation size alone currently does not identify owners.
* The native benchmark snapshot had 671,728 bytes of allocator-free MEM1 and
  51,380,064 bytes of allocator-free MEM2. Unallocated system arenas are
  separate figures, not additional allocator capacity. This is one benchmark
  snapshot, not the application's worst-case workload or fragmentation profile.
* The existing release ELF reports 3,599,774 bytes of text, 2,167,988 of data
  and 977,184 of BSS through `powerpc-eabi-size`: approximately 6.43 MiB before
  runtime heaps and framebuffers. Its loaded sections are in MEM1. These tool
  categories include read-only/unwind sections; they are not just source code
  and mutable variables. Debug sections in the ELF are not loaded Wii RAM.
* Important static owners include the 256 KiB GX FIFO, 128 KiB main stack and
  approximately 201 KiB network packet pool. Treat SDK-owned objects as
  reservations; do not resize them from a symbol-size listing alone.
* [ArchiveSafety.cpp](source/ArchiveOperations/ArchiveSafety.cpp) currently
  caps a budget at 16 MiB and half the summed free application heaps. This
  does not establish the largest contiguous allocation or reserve memory
  against simultaneous FTP/media activity.

Cached MEM1/MEM2 is the normal CPU path. The measured uncached read penalty
rules out converting general-purpose buffers to K1. Hot 8 KiB read results
mostly measure cache reuse; they do not justify moving every object to MEM1.

## 1. Make allocator contracts safe before changing placement

Work in [mem2.cpp](source/Memory/mem2.cpp) and
[mem2alloc.cpp](source/Memory/mem2alloc.cpp), with production-function host
regressions where possible and target checks for 32-bit address behavior.

* Guard `calloc(n, size)` multiplication before either heap is attempted.
  Its MEM2 fallback currently multiplies unchecked and placement tests only
  `size`, rather than the complete allocation.
* Give `realloc(p, 0)` one documented contract consistent across wrappers.
  The MEM1 fallback can inspect/free `p` after a real zero-size realloc has
  already freed it. MEM2 currently rounds zero to a small allocation; test
  that difference explicitly. Failed nonzero realloc must retain the original.
* Validate size rounding and arena arithmetic without overflowing or forming
  out-of-range pointers. Test pool boundaries, alignment, split/coalesce,
  fragmentation, cross-pool realloc and allocation failure.
* Correct the zero-length memset in `CMEM2Alloc::clear()`; first verify callers
  and intended reset semantics. Preserve the HBC gap and arena ownership.
* Keep canonical cached allocation pointers for ownership/free/realloc.
  Never pass a K1 alias to these wrappers. Audit pointer classification against
  actual owned ranges before tightening it; some SDK allocations may differ.

Gate: host sanitizers, debug/release builds, Dolphin allocation-failure and
exit checks pass. No placement experiment depends on an unsafe allocator.

## 2. Account for memory by owner and lifetime

Extend existing grouped probes, without a new allocation-tracking framework.
At explicit workload transitions record each bank's used/free bytes, largest
allocatable block, operation peak, allocation failures and stack high-water
marks. MEM2 free totals must remain distinguishable from contiguous capacity.

Use cheap owner counters at debug probe level 1, snapshot/fragmentation scans
at level 2, and integrity/canary checks at level 3. Compile this instrumentation
out of release; no idle polling or diagnostic allocations. Account for the
diagnostic storage itself. Do not scan heaps while holding GUI locks or per
frame during normal rendering.

Capture startup, browsing, HOME overlay, image/GIF/PDF viewing, movie/audio,
copy, each archive backend, FTP enable/disable, and exit. Include combinations
the application permits, especially transfers while rendering or playing audio.
Repeat open/close and enable/disable cycles to distinguish leaks from retained
caches and fragmentation.

Budget rule for each bank: measured persistent use + peak permitted transient
use + measured headroom must fit allocatable capacity. Record the largest
single allocation as a separate requirement. Set numeric headroom only after
these runs, including the temporary MEM1 HOME framebuffer. A budget check is
not a reservation: simultaneous operations must charge a shared allowance or
be serialized through existing task ownership before consuming it.

## 3. Place selected bulk buffers in MEM2

Use the existing explicit bank APIs, with their matching free/realloc paths.
Move one owner per change; measure peak RAM and whole-operation time before
and after. Keep the global allocation preference unchanged initially.

| Owner / source | Current footprint or lifetime | Proposed policy |
| --- | --- | --- |
| XFBs and HOME overlay, `video.cpp` | Two mode-sized XFBs, one temporary overlay | Keep in MEM1, VI requires it; track peak and handle failure |
| GX FIFO, `video.cpp` | 256 KiB static | Keep placement/size until GPU evidence supports a change |
| Image/GIF/PDF textures, `gui_imagedata.cpp`, image converters, `PDFViewer.cpp` | Often width × height × format, sometimes decoded and converted copies | Candidate for cached MEM2; validate GX accessibility, lifetimes and flushes |
| Movie frames, `WiiMovie.cpp` | Up to eight width × height × 2-byte frames | Cached MEM2 candidate; bound combined frame/audio/decoder peak |
| File copy, `fileops.cpp` | Default 128 KiB, current maximum 256 KiB | Cached MEM2 candidate; keep measured 128 KiB default |
| ZIP/RAR I/O, `ZipFile.cpp`, `RarFile.cpp` | ZIP 50/70 KiB paths; RAR 64 KiB store buffer | Cached MEM2, reused within an operation |
| 7z/U8/RARC, archive sources | Solid decoded blocks or compressed + decoded images | Cached MEM2, explicit aggregate/contiguous budgets before allocation |
| FTP, `FTPServer.cpp`, `FtpsrvConfig.h` | 32 KiB worker stack; four sessions; one shared 32 KiB core transfer buffer plus session state | Allocate only when enabled; measure full core size and reclaim on disable |
| Fonts, `FontSystem.cpp` | Main font already explicitly in MEM2 | Retain; measure glyph-cache growth before choosing eviction |
| Audio and worker stacks | Decoder blocks and live thread stacks | Retain first; measure latency and stack high-water before placement/resizing |

Do not create a blanket fallback that lets bulk owners consume required MEM1
headroom. Prefer a clear, recoverable OOM result when the selected bank cannot
honor an owner's budget. Audit movie dimension changes and allocation failure
before moving its buffers: current frame conversion follows an unchecked
allocation, and frame reallocation is triggered by width changes alone.

Gate: peak MEM1 pressure improves, MEM2 stays bounded, no flicker, underrun,
stale texture, corrupted output, crash or exit regression. Disabled FTP retains
no worker, sockets, core arena, device scans or polling. Native FTP passive
connection timeout remains unresolved; fix that before claiming FTP throughput.

## 4. Reduce copies and competing transient allocations

Reuse existing ZIP/RAR operation buffers across members; avoid per-member
allocation where the owner already has a reusable buffer. Separate concurrent
owners rather than introducing an unsafe process-global scratch buffer.

Audit [WiiArchive.cpp](source/ArchiveOperations/WiiArchive.cpp)'s memory-open
copy and U8/RARC compressed-plus-decoded residency. Consider an internal
ownership transfer only where the caller can relinquish its buffer and all
success/error/cancel paths remain explicit. Retain copying for borrowed input.
Count compressed input, output, parser metadata, decoder workspace and library
allocations together. Keep ZIP/RAR streaming and transactional publish rules.

Avoid decoding at unnecessary image dimensions where the existing library API
supports the required display result. Bound caches by bytes with predictable
eviction only after growth is measured; do not invent caches for this plan.
Throttle existing progress updates independently of I/O block sizes.

Gate: byte-identical archive/copy results, originals survive failure/cancel,
empty entries remain correct, and repeated operations recover their memory.

## 5. Tune working sets and CPU/device handoffs with evidence

First move only proven frequently reused state or scratch to MEM1, when its
measured bank headroom allows it. Fit the active input/output/tables together:
32 KiB L1 D and 256 KiB L2 are shared working resources, not per-buffer budgets.
LC halves the normal L1 data cache; leave it disabled in production initially.

For CPU-written GPU/audio/DMA data, flush before handing ownership to the
device. For device-written data, prepare the cache safely before the write and
invalidate after completion before CPU reads; never discard unrelated dirty
bytes sharing a cache line. Use 32-byte aligned ownership boundaries. Preserve
existing GX completion before freeing/reusing referenced storage. Add bounded
dirty-range tracking only where repeated redundant flushes are measured.

Run cached/uncached experiments on genuinely write-only, device-consumed
buffers, keeping ownership in K0 and avoiding simultaneous inconsistent aliases.
Time the complete producer, cache maintenance, consumer and synchronization.
The current fast scalar K1 writes are insufficient evidence to change memcpy,
textures or file-copy policy. Likewise, LC DMA is a later isolated experiment;
include setup/drain, reduced normal cache and failure cleanup in the measurement.

Benchmark 8–512 KiB and larger working sets where capacity permits, cold and
warm reuse, conflicting strides, real copy/CRC/texture conversion, and active
audio/GPU/FTP combinations. Compare median and tail latency, bytes copied,
peak/contiguous memory and correctness. Keep a change only when the real
workload improves without compromising resources or compatibility.

## Delivery and validation

Recommended PR order: allocator correctness; owner/fragmentation probes;
image/movie safety and placement; transfer buffers; archive residency/budgets;
then individual cache/copy experiments. Each PR includes a before/after owner
budget and the smallest relevant regressions. Defer linker section moves,
exception/unwind removal, stack shrinking, FIFO resizing and global heap-policy
changes until measurements and library contracts justify them.

Run `make check`, debug and release builds. Test the exact frozen DOL in an
isolated Dolphin profile first, capturing exceptions, hangs, teardown and GPU
behavior. Only after that passes, submit the same artifact through the shared
Wii dev queue server. Use [DEBUGGING.md](DEBUGGING.md) and
[MEMORY.md](MEMORY.md) for the existing tooling and benchmark procedure.

Exercise low-memory, fragmentation, short I/O, cancellation, repeated workloads,
device removal where supported, FTP disabled/enabled/re-enabled and exit to HBC.
Require zero output corruption and no progressive memory loss; verify release
has no diagnostic/background overhead. Physical Wii testing is required for
bandwidth, cache coherence, VI/GX/audio timing and any LC change. Dolphin timing
cannot substitute for those measurements.
