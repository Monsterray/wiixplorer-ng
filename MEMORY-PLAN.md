# Memory optimization plan

Status: allocator correctness implemented in v0.1.8; initial explicit-owner
accounting implemented in v0.1.9 and extended to static GUI textures and
DirList path strings in v0.1.10. Decoder/container accounting and placement
stages remain planned. The original sequence is based
on the v0.1.6 source audit and measurements in [MEMORY.md](MEMORY.md).

### Implemented foundation (v0.1.8)

* Checked calloc products and total-byte routing; defined zero-size realloc
  as free-and-return-NULL in both banks; preserved failed nonzero realloc input.
* Checked arena arithmetic and pool capacity before forming pointers; recovered
  exact-fit allocations, earlier-hole realloc fallback and shrink coalescing.
  Reset now clears the actual pool under its mutex, and free-space counts exclude
  the header required for a subsequent allocation.
* Added `MEM2_largestblock()` as an explicit snapshot, not an idle scan. Native
  capacity reports now include it; blank MEM1/LC fields mean not measured.
* Dolphin target tests exposed an installed Newlib realloc overflow return
  that leaves the MEM1 malloc lock held. Shared wrapper/direct-bank guards reject
  requests above `INT_MAX - 32` before reaching that backend. This is a signed
  allocator representation limit with alignment/metadata headroom, not a file
  size limit. No shared SDK modification was required.
* Added sanitized production-pool tests, cross-pool/failure preservation,
  boundary routing and 10,000 deterministic mixed allocation lifetimes, plus
  debug-only target checks integrated into the existing memory benchmark.

Host `make check` and debug/release builds passed. The corrected frozen DOL
passed Dolphin profile `build/dolphin.Ts7TNY`, then shared queue-server job
`20261004-162324-dc9036` on the physical Wii (65 seconds, HBC 1.10.0). Native
artifacts are in ignored `build/wii.xk98z645`. Both runs passed all 144 memory
operations, agent UI/file checks and exit; the native job restored settings and
probe files. Earlier diagnostic hangs are not successful validation evidence.

At this native snapshot, MEM2 had 51,380,000 free payload bytes but a largest
block of 28,311,360 bytes. MEM1 allocator-free was 671,936 bytes. These remain
single workload snapshots; no owner budget, allocation placement, transfer
buffer default, production LC use or CPU/device cache policy has changed.
Release linking removes the unused benchmark and largest-block diagnostic
functions. Per-owner peaks, concurrency reserves and stack accounting are next.

### Initial owner accounting (v0.1.9)

The existing grouped probes now account for copy I/O, ZIP compression and
extraction I/O, stored RAR I/O, 7z SDK allocations, FTP core/worker stack and
HOME overlay lifetimes. They record requested live/peak bytes, allocation and
release counts, failures, largest request and accounting errors separately for
MEM1 and MEM2. Failed allocations have an unknown bank. This is explicit owner
accounting, not a complete allocator census: full RAR decompressor, textures,
media decoders, fonts and browser metadata are not yet attributed.

Level 1 enables cheap owner counters in the corresponding IO, NETWORK or GPU
probe group. CPU level 2 takes transition snapshots of MEM1 allocator used/free
bytes, MEM2 used/free bytes and largest contiguous MEM2 capacity; THREADS level
2 prefills and measures the owned FTP stack only after its worker is joined.
Level 3 also checks MEM2 integrity. Other thread stacks are not measured yet.
Snapshots occur at startup, HOME/copy/archive operations, FTP lifecycle and
shutdown; there is no idle heap scan or new worker. Disabled FTP allocates no
FTP buffers and does no stack scan, enumeration or socket polling.

The summed fixed counter/stack/snapshot storage is 1,821 bytes on Wii,
excluding linker alignment, code, constant strings and temporary stack/stdio
use. Eight fixed snapshot slots
bound history; overflow increments a reported drop count. The existing main
thread probe flush writes `sd:/apps/WiiXplorer/memory-probes.csv` only after
an event, with a 64 KiB report bound. An unavailable SD file retains pending
counters; a write/close error stops further appends so a partial batch is not
silently extended. No diagnostic storage or calls remain in the release ELF.

Owner bytes are requested capacities, not padded allocator consumption. The
7z SDK owner includes its existing budget headers. MEM2 used bytes are pool
payload capacity minus free payload, so additional allocator headers count as
used; MEM1 values come from Newlib `mallinfo`. These are independent heap
snapshots, not an atomic reservation against concurrent allocations. MEM1's
largest contiguous block remains unmeasured.

The final level-3 DOL passed Dolphin archive profile `build/dolphin.RNOsCm`
(30 codec/parser/CRC/traversal/preservation cases) and copy profile
`build/dolphin.VtuiDR`, including HOME and completed exit. The final owner rows
had zero live bytes and no accounting or heap-integrity errors. Observed
individual MEM1 peaks were 70 KiB for ZIP I/O, 64 KiB stored RAR, 171,912 bytes
for 7z SDK, 256 KiB for the copy benchmark's buffer sweep and 600 KiB for HOME.
FTP profile `build/dolphin.4ksPi3` also passed SD roundtrip/authentication,
append/resume and idle handling; USB was absent in that emulator profile. FTP
core requested 71,032 bytes, its worker stack 32 KiB, and the measured stack
high-water was 9,808 bytes. Host FTP tests covered both fake SD/USB devices,
failed startup, disable/re-enable and zero live owner bytes after shutdown.
These peaks are workload observations, not concurrent capacity budgets or
physical bandwidth measurements. Native FTP passive timeout remains a separate
unresolved issue; these tests do not establish native FTP throughput.

Shared Wii dev queue job `20261006-001138-5ca9af` passed the same frozen
archive DOL on physical hardware (190 seconds), returned to HBC 1.10.0 and
restored the original SD settings/reports. Artifacts are in ignored
`build/wii.wbsoi_0v`. All final owner live bytes were zero, with no accounting
or MEM2 integrity errors; observed owner peaks matched the Dolphin archive
run. The ring reported 25 dropped transition snapshots during the rapid
fixture batch, so its history is explicitly incomplete; owner counters remain
cumulative. MEM2 was 51,380,000 free bytes with a 28,311,360-byte largest block
at both startup and shutdown. These observations do not establish media or
concurrent-workload reserves.

Physical copy queue job `20261006-001227-164451` passed 15 checksum-verified
8 MiB transfers, HOME controls and exit to HBC (250 seconds); original SD
files were restored. Artifacts are in ignored `build/wii.vs6f5k5o`. Copy and
HOME owners ended at zero live bytes, with no accounting or integrity errors.

| Copy buffer | Median SD copy MiB/s | Verified samples |
| --- | ---: | ---: |
| 32 KiB | 2.014 | 3 |
| 64 KiB | 1.944 | 3 |
| 70 KiB | 1.812 | 3 |
| 128 KiB | 2.069 | 3 |
| 256 KiB | 2.175 | 3 |

This small sample shows approximately 5% improvement at 256 KiB over the
128 KiB default while doubling requested capacity. Retain the default until
repeated SD/USB and concurrent-workload measurements justify the tradeoff.
This change adds observability, not a measured production speed improvement.
Host `make check`, level-3 and default level-1 debug builds, and release passed.
Release symbol inspection found no memory-probe or heap-snapshot functions.

The full rebuild also exposed a WiiLoad initialization bug: `memset(&Item, ...)`
overwrote a pointer and adjacent stack rather than the allocated item. Value
initialization fixes it; the production receive function has an ASan/UBSan
regression covering accepted, rejected and failed receives.

Production bank placement, cache aliases, LC use and buffer defaults remain
unchanged. Next, extend accounting to media/browser owners and permitted
workload combinations, then establish reserves before moving individual bulk
owners to cached MEM2. Do not infer safe stack reductions from one FTP run.

### Texture and directory lifetimes (v0.1.10)

GPU level 1 now accounts for `GuiImageData` static decoded RGBA8 and TPL
texture allocations, including retained resources and repeated replacement.
A debug-only requested-size field adds four bytes per Wii `GuiImageData`
object; release layout and instrumentation overhead remain unchanged. IO
level 1 counts `DirList`/`DirListAsync` owned path strings. Vector capacity,
FileBrowser's separate item metadata, libgd decoded images, animated GIF
frames and decoder workspace remain unattributed. Do not treat these counters
as the entire image/browser memory footprint.

The summed fixed probe storage increases to 2,173 bytes (excluding alignment,
code/strings and temporary I/O/stack use). The ten-owner maximum row batch still
fits the reserved 10 KiB within the existing 64 KiB report limit. No new worker,
idle scans, allocation registry or release probes were introduced.

Production-function ASan/UBSan tests reproduced and fixed an animated-image
reload leak, stale dimensions/format after a failed decode, and directory
normalization using a string length captured before duplicate slashes were
removed. The directory comparator now returns false for case-insensitive
identical paths, as required by `std::sort`'s strict ordering contract. Tests
cover GIF-to-GIF/PNG/TPL replacement and destruction, invalid image decoding,
normalized device roots and balanced path/texture counters at levels 0 and 1.
Codec decoding in these lifetime tests is stubbed; they do not validate the
legacy GIF/TPL parsers or GPU consumption timing.

Final level-3 Dolphin profile `build/dolphin.6RiBMS` passed UI/browser controls,
HOME, file roundtrip, exception checks and completed guest/core exit. GUI
textures peaked at 1,346,624 requested MEM1 bytes (46 allocation/release pairs),
HOME at 614,400 bytes, and both ended at zero. No accounting or MEM2 integrity
errors were reported. DirList path strings were covered by host tests; this
smoke workflow did not create that owner on target.

Shared queue job `20261006-003555-54844b` passed the exact frozen DOL on
physical Wii (66 seconds), returned to HBC 1.10.0 and restored original SD
settings/reports. Artifacts are in ignored `build/wii.2lweru85`. GUI texture and
HOME owners returned to zero, without accounting or MEM2 integrity errors.
Host `make check`, debug level 3 and release builds passed; release symbol
inspection confirmed the memory probes are absent. Real animated-image reload,
malformed media and concurrent viewer/transfer workloads still require target
validation after their decoder/ownership audits.

Audit follow-ups before placement experiments: movie frame reallocation tests
must include height-only changes, allocation failure and render/decode/GX
ownership; its decoder currently converts through an unchecked allocation.
Legacy GIF/TPL metadata parsing and PDF page dimension/allocation arithmetic
also need dedicated malformed-input tests before claiming bounded decoding.
Font-file reads still need checked seek/size/read/close behavior. Extend owner
coverage there separately, retain existing bank/cache/buffer policies, and
collect real viewer/decoder plus concurrent transfer workloads before setting
numeric reserves.

Correctness and data safety come first, followed by bounded resources,
compatibility and measured performance. Keep changes confined to individual
owners and existing helpers; no allocator replacement or broad UI refactor.

## Baseline at the original v0.1.6 audit

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
  At the baseline, its MEM2 fallback multiplied unchecked and placement tested only
  `size`, rather than the complete allocation.
* Give `realloc(p, 0)` one documented contract consistent across wrappers.
  The baseline MEM1 fallback could inspect/free `p` after a real zero-size realloc
  had already freed it. MEM2 rounded zero to a small allocation; test
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
