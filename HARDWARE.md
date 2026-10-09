# Wii hardware research map

Research snapshot: 2026-10-08. This reference consolidates WiiXplorer's measured
hardware behavior and points to the complete research, implementation and data.
It describes this application's tested workloads, not universal Wii performance
limits. Historical measurements retain their original versions and SDKs.

## Research and evidence index

| Topic | Authoritative project record | Implementation / reproduction |
| --- | --- | --- |
| MEM1/MEM2 aliases, caches, LC DMA, scalar and complete working-set measurements | [MEMORY.md](MEMORY.md) | `source/Diagnostics/MemoryBench.cpp`, `tests/memory_bench.py` |
| Allocator safety, ownership census, fragmentation, media placement, remaining experiments | [MEMORY-PLAN.md](MEMORY-PLAN.md) | `source/Memory/`, `source/Diagnostics/MemoryProbes.cpp`, `tests/memory_allocator.py`, `tests/memory_probes.py` |
| SD/USB speeds, mount caches, IOS/cIOS paths, filesystem and partition limits | [STORAGE.md](STORAGE.md) | `source/DeviceControls/`, `source/mload/usb2storage.c`, `tests/storage_bench.py` |
| File/network buffers, transactional writes, native IOS send integrity and throughput | [TRANSFERS.md](TRANSFERS.md) | `source/FileOperations/fileops.cpp`, `source/network/TransferSocket.cpp` |
| Historical HBC hardware investigation, IPC, compression pipeline and scheduling | [HBC-NETWORKING.md](HBC-NETWORKING.md) | Pinned primary-source links in that record; current SDK pin in `scripts/build-hbc-agent.py` |
| FTP resources, lifecycle, unresolved physical data connections | [FTP.md](FTP.md) | `source/FTPOperations/FTPServer.cpp`, `source/FTPOperations/ftpsrv/` |
| Decoder working memory, budgets, format limits and corruption checks | [ARCHIVES.md](ARCHIVES.md) | `source/ArchiveOperations/`, `tests/native_archive_bench.py` |
| Probe groups, exact artifact capture, emulator gate, shared physical-Wii lease and HDMI | [DEBUGGING.md](DEBUGGING.md) | `scripts/validate-bench.py`, `scripts/hbc-smoke.py`, `scripts/check-dolphin-smoke.py` |
| Toolchain/library revisions, patches and redistribution | [DEPENDENCIES.md](DEPENDENCIES.md), [LICENSE.md](LICENSE.md) | `scripts/build-deps.py`, `scripts/patches/` |
| Latest validated scope and release blockers | [RELEASE-CANDIDATE.md](RELEASE-CANDIDATE.md) | Historical successful jobs do not supersede its current blockers |

## Memory and CPU model

| Resource | Established capacity / behavior | Consequence |
| --- | --- | --- |
| MEM1 | 24 MiB physical; cached `0x80000000–0x817FFFFF`, uncached `0xC0000000–0xC17FFFFF` | Loaded executable sections, stacks, VI buffers and hot CPU data compete for space |
| MEM2 | 64 MiB physical; cached `0x90000000–0x93FFFFFF`, uncached `0xD0000000–0xD3FFFFFF` | Bulk capacity; the application's arena is smaller and contains reservations |
| L1 instruction / data | 32 KiB each, 8-way, 32-byte lines | Code footprint and the combined active data footprint matter |
| L2 | 256 KiB, 2-way, 64-byte lines | Repeated 256 KiB reads can benefit from cache; this is not raw RAM bandwidth |
| Locked cache | 16 KiB carved from L1 data, leaving 16 KiB normal data cache | LC consumes a working resource and needs complete-pipeline validation |

Sources and architectural qualifications are in [MEMORY.md](MEMORY.md): native
boot-info capacity, IBM 750CL architecture used as Broadway's cache reference,
and libogc/Dolphin implementation links. CPU accesses use cached storage by
default. K0/K1 are aliases of one allocation; ownership remains with its cached
pointer. Converting an address neither allocates memory nor transfers ownership.

`Application.cpp` requests a 52 MiB MEM2 pool. `mem2.cpp` respects the live arena,
starts no earlier than `0x90200000`, caps the upper end at `0x93300000`, and
splits allocation around HBC-Reborn's retained range. With the pinned 1.10.2
SDK, `[0x91800000, 0x91801140)` reserves 4,416 bytes for netlog/crash/last-log.
Physical capacity, unallocated SYS arena, allocator-free payload and largest
contiguous allocation are different quantities. They cannot be added into an
allocation guarantee. Historical snapshots of roughly 51.38 MB free MEM2 with
only a 28.31 MB largest block demonstrate the distinction; the new reservation
also makes earlier capacity snapshots historical.

Wrapped allocation normally tries MEM1 then MEM2. The optional >30 KiB MEM2
preference remains off. Explicit bank allocation has a matching bank free/realloc
path. Checked products, alignment arithmetic, zero-size realloc and preservation
on failed nonzero realloc are allocator contracts. Requests above `INT_MAX - 32`
are rejected before the installed Newlib backend; this is an allocator limit,
not a universal file-size limit. `WxMemoryBudget()` is an operation snapshot of
half the summed allocator-free bytes, not an atomic concurrency reservation.

## What the measurements support

The full matrices, repetitions, timing boundaries, verified job IDs and failed
attempts live in [MEMORY.md](MEMORY.md). Representative native findings:

| Experiment | Observation | Supported interpretation |
| --- | --- | --- |
| v0.1.5, 256 KiB scalar reads | MEM1 K1 71.097 MiB/s; MEM2 K1 19.805 MiB/s; cached reads about 1,200 MiB/s | Uncached CPU reads are expensive; cached repetition is not external RAM bandwidth |
| v0.1.11, MEM2 reused copy plus CRC | Cached output 143.12 MiB/s at 128 KiB, 50.38 at 256 KiB, 39.25 at 1 MiB | Combined input/output/consumer working set changes performance sharply |
| Same pipeline, uncached output | 61.66 MiB/s at 128 KiB; 40.55 at 1 MiB | Scalar K1 write speed does not establish an end-to-end improvement |
| 512 KiB MEM2 reused reads | Sequential 137.65 MiB/s; 4096-byte strides 18.68 MiB/s | Compact contiguous access is preferable for this measured workload |
| LC DMA, 8 KiB chunks | MEM1→LC 1348.845; MEM2→LC 439.996 MiB/s | Transfer-only timing excludes maintenance, setup and processing; production LC remains off |

The original native suite verified 144 operations. The later complete working-set
suite adds 768 rows over 8 KiB–1 MiB, cached/uncached outputs, cold/reused copy+CRC
and 4/32/512/4096-byte strides. Three samples per case provide medians and maxima,
not robust tail-latency estimates. Dolphin validates control flow and correctness;
it cannot establish physical RAM, DMA, disk or Wi-Fi throughput.

LC benchmark repairs preserve the `0xE0000000` tag in DMAL, MEM2 physical bit 28,
and read DMAQL as `(HID2 >> 24) & 15`. They are debug-only workarounds for the
inspected libogc helpers. LC tests preserve CPU state, refuse existing LC use and
bound queue drains. These results do not justify replacing shared SDK routines
or enabling production LC.

## Device ownership and current placement

CPU-written GPU/audio/DMA buffers require cache publication before the consumer
owns them. Device-written buffers require a safe cache preparation before the
write, completion synchronization and invalidation before subsequent CPU reads.
Cache operations use cached addresses and exclusively owned, 32-byte-aligned
ranges so an invalidation cannot discard neighboring dirty data. Cache coherence,
CPU thread publication and device completion are separate obligations.

| Owner | Current project policy | Relevant source |
| --- | --- | --- |
| Copy I/O | Cached MEM2, 128 KiB default, smaller same-bank OOM fallbacks; explicit requests up to 256 KiB | `source/FileOperations/fileops.cpp` |
| PDF texture | Cached MEM2; pixmap stays MEM1; publication on rendering thread | `source/TextOperations/PDFViewer.cpp` |
| Movie frame textures | Cached MEM2; workers joined and GX fenced before reuse/free | `source/VideoOperations/WiiMovie.cpp` |
| XFBs / HOME overlay | MEM1, VI requirement; XFB device pointers are K1 aliases of SDK framebuffers | `source/VideoOperations/video.cpp` |
| GX FIFO | Existing 256 KiB static aligned buffer | `source/VideoOperations/video.cpp` |
| Audio buffers, ordinary GUI textures, stacks | Existing placement; further moves require owner-specific evidence | `source/SoundOperations/`, `source/GUI/gui_imagedata.cpp` |

PDF texture placement moved a 969,408-byte request out of MEM1 without a claimed
speed gain. Copy placement similarly relieves MEM1 pressure; three measured copy
samples do not establish acceleration. XFB dimensions depend on video mode;
HOME's temporary framebuffer participates in the peak, even if short-lived.
GX texture dimensions in the current paths are bounded to 1–1024. RGBA8 conversion
uses GX layout rather than assuming linear RGBA bytes. PDF pixmap plus texture,
movie audio/frame queues and GIF workspace plus old/new residency must fit together.

The 24 debug owner counters record requested capacities, not a complete library
allocation census or padded heap consumption. Fixed probe storage is 4,637 bytes
on Wii, excluding code/strings/alignment and temporary I/O. Transition history is
bounded and can drop entries; cumulative owner counters remain useful. Observed
stack high-water values from small fixtures are not worst-case codec bounds.
Release omits this diagnostic instrumentation.

## Storage, IOS and network constraints

[STORAGE.md](STORAGE.md) records the tested IOS58 revision, SDK, FAT32 geometry,
separate read/write/copy speeds and interleaved repeats. Roughly 7 MiB/s reads,
3–4 MiB/s writes and 2 MiB/s same-device copies on those drives are application
observations. USB buffer rankings reversed across runs; 128 KiB remains the
current copy default. Mount cache parameters describe 256 KiB payload at
512-byte sectors, excluding bookkeeping. The official IOS USB path and local
cIOS path differ; the latter chunks at 64 sectors and uses MEM2 scratch for MEM1
buffers. Application block size does not imply a single matching device request.

[TRANSFERS.md](TRANSFERS.md) and [HBC-NETWORKING.md](HBC-NETWORKING.md) distinguish
native IOS send misreporting from Dolphin host behavior. Current native sends
poll adequate capacity and use 4 KiB chunks; receives use 16 KiB. The framed
HBC path retains blocking mode across frames, checked CRC and a fixed two-slot
64 KiB pipeline. Timing includes framing/compression differences; decimal MB/s
in historical HBC research differs from binary MiB/s in this project. Channel
scheduling priorities and its zlib arena do not automatically apply to the SDK.

Filesystem compatibility and per-file/API limits remain independent of RAM.
GPT discovery does not remove 32-bit sector interfaces; historical EXT features
are limited; exFAT is not an established application mount path. Existing
transactional replacement, checksum verification, bounded waits and cancellation
are part of the tested behavior.

## Evidence gaps and next useful measurements

The current [testing-build record](RELEASE-CANDIDATE.md) identifies native FTP
passive/control connection failures and intermittent Dolphin ISI/unknown-instruction
faults after cleanup. Successful historical exits do not resolve those blockers.
Audible audio behavior, full-motion flicker review, physical SMB/NFS paths and
permitted concurrent audio/GPU/transfer peaks remain incomplete.

Useful next comparisons isolate one owner or policy and time the complete
producer, copies, cache maintenance, device consumer and synchronization. Record
frame-time impact, throughput, peak requested bytes, free/contiguous capacity,
allocation failures and repeated teardown recovery. Numeric concurrency reserves,
stack reductions, GPU/audio K1 policies, production LC, FIFO resizing and global
allocation rerouting remain experiments pending such evidence.

Exact reproduction commands and lease requirements are in [DEBUGGING.md](DEBUGGING.md).
The current workflow runs host checks and the matching Dolphin gate before
queuing that same frozen DOL on the physical Wii; guest exceptions and missing
core shutdown fail the gate. Hardware data and build artifacts remain Git-ignored.
