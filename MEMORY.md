# Native memory measurements

The physical Wii benchmark is **pending**. On 2026-10-03, one attempt failed
to start the application, another started but produced no completion marker,
and a third timed out uploading the DOL. The Wii then stopped responding;
the operator cannot currently reboot it. These attempts provide no valid
memory speed measurements or console-specific capacity report.

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
is architectural; it is not dynamically detected. No live capacity report has
yet been retrieved from this application.

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

Failed profiles are `build/wii.1s6qxryf`, `build/wii.vpmb_2mu` and
`build/wii.tb9_2p1w`. The second retained a successful application startup
without a report. No failure has established a specific LC defect. Argument
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
No memory-speed result is validated. The debug runner now persists its CSV
header and each completed timing row outside timed regions, so another native
failure retains the last completed operation. The controller also captures
failure status/framebuffer before exiting where the agent remains responsive.

After HBC recovery/settings restoration, job `20261004-024106-510554` reruns
without optional network log forwarding to isolate that variable. Its frozen
DOL is recorded in ARCHIVES.md. Queuing it is not a passing result.
