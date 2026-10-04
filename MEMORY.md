# Native memory measurements

The physical Wii benchmark passed all 48 verified operations on 2026-10-04,
followed by normal UI/file checks, exit to HBC and restoration of original
settings. Every hardware operation used the shared Wii queue-server lease,
and the exact DOL first passed the same checks in Dolphin. See the measured
results below; emulator timings are not used as physical bandwidth.

## Capacity

| Region | Standard retail Wii capacity | Benchmark footprint |
| --- | ---: | ---: |
| MEM1 | 24 MiB (25,165,824 bytes) | Two 256 KiB buffers |
| MEM2 | 64 MiB (67,108,864 bytes) | Two 256 KiB buffers |
| Locked cache (LC) | 16 KiB (16,384 bytes) | 8 KiB |

MEM1/MEM2 capacities follow Dolphin's [hardware memory constants](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/HW/Memmap.h).
Development hardware can have different capacities. LC is part of the CPU data
cache, rather than additional system RAM; libogc's [initialization](https://github.com/devkitPro/libogc/blob/master/libogc/cache_asm.S)
locks 512 cache lines of 32 bytes each.

The native `memory-capacity.csv` reads IOS boot-info fields for physical and
simulated MEM1/MEM2 sizes and arena limits, using the offsets documented in
[Dolphin's IOS implementation](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/IOS/IOS.cpp).
It separately records remaining SYS arena space and allocator free bytes before
the benchmark. These are different from physical capacity: IOS, application
code, resources and allocator reservations reduce usable memory. LC capacity
is architectural; it is not dynamically detected. Native reports confirmed the
MEM1/MEM2 capacities above.

## Benchmark and interpretation

`make debug PROBE_LEVEL=3` includes the explicit `--memory-bench=<new sd:/directory>`
entry point. It is compiled out of release builds and never runs during ordinary
startup. The benchmark object uses `-O2` while the rest of debug uses `-Og`.
It allocates 512 KiB in each RAM bank, verifies alignment and bank addresses,
uses different deterministic source patterns to detect address aliasing, and
releases its buffers before writing the completion marker.

Each operation processes 8 MiB, repeated three times, for 48 CSV rows:

- `memcpy`: all four MEM1/MEM2 directions, repeated 256 KiB blocks. Destination
  cache flush is timed; final CRC verification is outside the timer.
- `crc32_cached`: repeated 256 KiB sources in each bank. This measures the CRC
  workload with cache effects, not uncached RAM bandwidth.
- `read32_hot` / `write32_hot`: volatile 32-bit CPU loops over an 8 KiB footprint
  in MEM1, MEM2 and LC, with LC enabled for all three comparisons. These measure
  hot CPU accesses, not sustained external-memory bandwidth.
- `dma_load` / `dma_store`: 8 KiB chunks between each RAM bank and LC. Timing
  sums command enqueue and queue drain; cache maintenance and verification of
  every chunk are outside timing. These are not end-to-end pipeline speeds.

The benchmark saves/restores LC-related BAT, HID2 and machine-check state,
refuses an already enabled LC, and bounds each DMA drain to 100 ms. Its debug
helper preserves MEM2's physical address bit 28 and reads DMAQL at HID2 bits
24..27. The installed official libogc 3.1.0 helpers instead clear four high
address bits and shift the queue field by four. Compare the official
[assembly](https://github.com/devkitPro/libogc/blob/master/libogc/cache_asm.S),
[queue implementation](https://github.com/devkitPro/libogc/blob/master/libogc/cache.c)
and [libogc2 assembly](https://github.com/extremscorner/libogc2/blob/master/libogc/cache_asm.S).
This workaround is confined to the benchmark; the shared SDK is unchanged.
Its native behavior still requires validation. Host sanitizer checks exercise
report verification, allocation failure, corrupted DMA, queue timeout and cleanup.

Dolphin is useful for functional checks but cannot establish physical LC DMA
speed: its [interpreter](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/PowerPC/Interpreter/Interpreter_SystemRegisters.cpp)
implements these transfers immediately with a simulated queue.

## Reproduction and recovery

On this shared bench, use the queue lease described in [DEBUGGING.md](DEBUGGING.md):

```sh
make debug PROBE_LEVEL=3
python3 "$HOME/.wii-bench/wiibench.py" add \
  --name wiixplorer-memory-speed --agent wiixplorer-ng --timeout 300 \
  --cwd "$PWD" -- python3 scripts/hbc-smoke.py --hardware --memory-bench
```

The runner saves reports and frozen binaries under ignored `build/wii.*`, checks
all 48 rows, prints median MiB/s per operation, removes owned reports, tests exit
and restores settings. `--build-dir` selects a frozen candidate instead of the
current debug build. Other contributors can use the application argument on
their own Wii and retrieve the two CSV reports from SD.

### Historical failures (superseded by the 0.1.4 results below)

Failed profiles are `build/wii.1s6qxryf`, `build/wii.vpmb_2mu` and
`build/wii.tb9_2p1w`. The second retained a successful application startup
without a report. At that stage no failure had established a specific LC defect. Argument
capture was moved before application initialization as a precaution, but its
effect could not be tested because the subsequent upload timed out.

Recovery job `20261003-150246-fe3ab2` is queued to restore settings from
`build/wii.tb9_2p1w` when HBC becomes available. Restoration after that failed
upload is unconfirmed. A frozen candidate under `build/memory-pending` is queued
after recovery as job `20261003-151400-d3d394`; its results must be reviewed
before claiming hardware success. Both debug/release builds and the full host
check suite passed; the final distinct-pattern change also passed the memory
sanitizer check. The release ELF has no `RunMemoryBenchmark` symbol.

The queued recovery completed successfully on 2026-10-04. The frozen memory
retry did not observe the app agent starting and did not finish its speed report.
Its retained capacity report (`build/wii.06_xbtov/after-memory-capacity.csv`)
confirms physical MEM1 = 25,165,824 bytes (24 MiB), MEM2 = 67,108,864 bytes
(64 MiB), and LC = 16,384 bytes (16 KiB). These are capacities, not speed results.
The MEM1 IOS arena column in that report is implausible and must not be treated
as a valid available-memory measurement; its boot-info field mapping needs
further verification. The allocator-free values are application snapshots.

The native report now validates IOS arena fields against the cached address
range of their physical bank. Unset/reversed/out-of-bank fields report zero
(unknown/unusable), rather than a cached address being misreported as gigabytes.
The historical invalid MEM1 arena value above remains untrusted. This changes
capacity reporting only, not the speed kernels or physical bank sizes.

Job `20261004-022103-7976c6` returned a valid capacity report but timed out
waiting for benchmark completion. Its retained report is in
`build/wii.qqd71gf1/after-memory-capacity.csv`; physical capacities match the
values above. MEM1's unset IOS arena now reports zero; MEM2's valid IOS arena
reports 56,489,984 bytes. These are not allocator-free totals or bandwidth.
That retry validated no memory-speed result. The debug runner then persisted its CSV
header and each completed timing row outside timed regions, so another native
failure retains the last completed operation. The controller also captures
failure status/framebuffer before exiting where the agent remains responsive.

After HBC recovery/settings restoration, job `20261004-024106-510554` reruns
without optional network log forwarding to isolate that variable. Its frozen
DOL is recorded in ARCHIVES.md. Queuing it is not a passing result.

## Dolphin-first follow-up, 0.1.3

All 48 production memory operations verified in the final clean Dolphin
candidate (`build/dolphin.UQ9HKS`), with normal UI/file/exit and zero reported
CPU/GPU integrity faults or guest exceptions. Emulator timings are deliberately
not presented as physical speeds or available Wii memory. Native retry
`20261004-024106-510554` was canceled pending emulator validation. The native
completion timeout remains unresolved; physical speeds still need measurement.

## Native results and DMA correction, 0.1.4

Durable CSV checkpoints (`fflush` plus `fsync`, outside timed intervals) retained
36 verified rows from failed job `20261004-104839-706391`. HBC recorded a machine
check at PC `8002fd80`, immediately after the first DMA command. The matching ELF
localized it to `MemoryDma`. Its DMAL word incorrectly stripped the high bits
of the LC address: `0xe0000000` became zero. LC DMA needs the cache tag address,
as shown by the installed libogc assembly and
[libogc2's LCLoadBlocks](https://github.com/extremscorner/libogc2/blob/master/libogc/cache_asm.S).
The corrected word preserves that address, while the RAM word retains MEM2's
physical bit 28. A production command-word host regression failed before this
fix and passed afterward. Report sync failure now stops before enabling LC.

The corrected DOL passed all 48 operations and UI/file/exit checks in Dolphin
(`build/dolphin.8yAVUk`), then native job `20261004-105910-ed3057` passed the same
sequence, returned to HBC 1.9.3 and restored settings. Native artifacts are
`build/wii.bff59o32`. This resolves the DMA machine check for this benchmark;
no release memory kernel or shared SDK was changed.

Each value below is the median of three verified runs, processing 8 MiB per run:

| Operation | Source → destination | MiB/s |
| --- | --- | ---: |
| memcpy, destination flush timed | MEM1 → MEM1 | 201.496 |
| memcpy, destination flush timed | MEM1 → MEM2 | 101.977 |
| memcpy, destination flush timed | MEM2 → MEM1 | 106.271 |
| memcpy, destination flush timed | MEM2 → MEM2 | 66.261 |
| Cached CRC32 | MEM1 → CPU | 218.204 |
| Cached CRC32 | MEM2 → CPU | 208.133 |
| Hot 32-bit reads | MEM1 / MEM2 / LC → CPU | 2215.453 / 2215.453 / 2218.525 |
| Hot 32-bit writes | CPU → MEM1 / MEM2 / LC | 924.749 / 925.069 / 925.605 |
| Queue-drained DMA load | MEM1 → LC | 1353.409 |
| Queue-drained DMA store | LC → MEM1 | 1459.854 |
| Queue-drained DMA load | MEM2 → LC | 440.844 |
| Queue-drained DMA store | LC → MEM2 | 1462.256 |

The CPU hot loops revisit 8 KiB and measure cache-resident access. DMA timing
excludes cache maintenance and verification. These workload measurements do
not establish uncached DRAM bandwidth or an application-wide speedup. No
production buffer size or allocation policy was changed based on them.

This run reported MEM1 24 MiB and MEM2 64 MiB physical capacity; LC is 16 KiB.
Allocator free space before the benchmark was 672,904 bytes in MEM1 and
51,380,064 bytes in MEM2. Unallocated SYS arena space was 13,901,824 and 749,376
bytes respectively; these are separate pools, not additive available-memory
promises. The unset MEM1 IOS arena reports zero (unknown); MEM2's IOS arena was
56,489,984 bytes. Each RAM bank contributed 512 KiB to the benchmark.
