# Wii memory and cache measurements

For the prioritized project changes, ownership policies and validation gates,
see [the memory optimization plan](MEMORY-PLAN.md).

The v0.1.8 allocator safety validation also passed all 144 operations in Dolphin
and on the queued dev Wii. Its new contiguous-capacity snapshot and implemented
fixes are recorded in the plan; the speed tables below retain the original
v0.1.5 measurement set for consistent comparison.

The v0.1.5 benchmark passed **144 verified operations** on the physical Wii on
2026-10-04, after the identical DOL passed Dolphin. UI/file checks, exit to HBC
1.9.6 and restoration of original settings/probes also passed. All dev-Wii
access used the shared queue-server lease. Emulator timings are not physical
bandwidth measurements.

The results favor compact cached working data and avoiding unnecessary copies.
Uncached reads were much slower, especially in MEM2; uncached destinations
performed well for some scalar copies. No production buffer, allocation or
cache policy has been changed based on these measurements.

## Memory capacity and aliases

| Region | Physical capacity | Benchmark allocation |
| --- | ---: | ---: |
| MEM1 | 24 MiB (25,165,824 bytes) | Two 256 KiB buffers |
| MEM2 | 64 MiB (67,108,864 bytes) | Two 256 KiB buffers |
| Locked cache (LC) | 16 KiB (16,384 bytes) | 8 KiB used |

Native IOS boot-info reports confirmed MEM1/MEM2 capacity. LC capacity is
architectural, not dynamically detected; it is part of the CPU data cache,
not additional RAM. Development hardware can differ. See
[Dolphin's boot-info fields](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/IOS/IOS.cpp)
and [libogc's LC initialization](https://github.com/devkitPro/libogc/blob/master/libogc/cache_asm.S).

K0 and K1 are cached and uncached effective addresses for the **same physical
allocation**, respectively. The benchmark uses libogc's
[`MEM_K0_TO_K1`](https://github.com/devkitPro/libogc/blob/master/gc/ogc/system.h),
never allocating or freeing an alias independently.

| Bank | Cached (K0) | Uncached (K1) | Physical |
| --- | --- | --- | --- |
| MEM1 | `0x80000000–0x817FFFFF` | `0xC0000000–0xC17FFFFF` | `0x00000000–0x017FFFFF` |
| MEM2 | `0x90000000–0x93FFFFFF` | `0xD0000000–0xD3FFFFFF` | `0x10000000–0x13FFFFFF` |

The latest capacity CSV recorded these source/destination alias pairs:

| Allocation | K0 | K1 |
| --- | --- | --- |
| MEM1 source | `0x80A7B880` | `0xC0A7B880` |
| MEM1 destination | `0x80ABB8A0` | `0xC0ABB8A0` |
| MEM2 source | `0x90200020` | `0xD0200020` |
| MEM2 destination | `0x90240040` | `0xD0240040` |

Physical capacity is not available heap. Before this run, allocator-free bytes
were 671,728 in MEM1 and 51,380,064 in MEM2; unallocated SYS arena bytes were
14,168,064 and 767,840. These are separate accounting categories, not an
additive allocation guarantee. MEM1's unset IOS arena reports zero (unknown);
MEM2's valid IOS arena was 56,489,984 bytes. Invalid arena ranges are rejected
rather than interpreting an address as a capacity.

## Cache hierarchy and interpretation

The cache organization below follows IBM's
[750CL datasheet, page 10](https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/7138/2156_IBMPPC750CLGEQ4024.pdf).
It is the architectural reference used here for Broadway's cache behavior.

| Cache | Capacity | Associativity | Line size | Purpose |
| --- | ---: | ---: | ---: | --- |
| L1 instruction | 32 KiB | 8-way | 32 bytes | Instruction fetch |
| L1 data | 32 KiB | 8-way | 32 bytes | CPU loads/stores |
| L2 | 256 KiB | 2-way | 64 bytes | Instructions and data, normally shared |

For normal cacheable accesses, the approximate path on successive misses is:

```text
Data:         CPU → L1 data → L2 → memory system → MEM1 / MEM2
Instructions: CPU → L1 instruction → L2 → memory system → RAM
```

Enabling LC partitions L1 data into **16 KiB normal cache plus 16 KiB locked
cache**, each four-way. LC is therefore a tradeoff, not free extra storage.
See [IBM's user manual, section 9.2](https://fail0verflow.com/media/files/ppc_750cl.pdf).
The original hot CPU tests run with LC enabled; the alias comparisons run after
LC state restoration, with the normal cache configuration.

An 8 KiB repeated read can fit in L1. A repeated 256 KiB read can benefit from
L2 reuse, so neither result establishes external-RAM bandwidth. A copy with
256 KiB cached input and 256 KiB cached output has a **512 KiB combined data footprint**,
before code and other active data. Capacity, associativity and buffer placement
can therefore affect copies differently from reads. Cache hits/misses were not
counted; these are explanations to investigate, not measured miss rates.

## Verified native results

All values below come from **one v0.1.5 run**, not a mixture of historical builds.
They are median MiB/s of three verified repetitions, each processing 8 MiB of
logical accesses. Copies count copied bytes, not combined read-plus-write bus
traffic. Repeated cached writes publish final buffer contents; they do not write
8 MiB of distinct physical memory. These are workload speeds, not DRAM ceilings.

Scalar CPU reads and writes (K0 cached, K1 uncached):

| Bank / alias | Read, 8 KiB | Write, 8 KiB | Read, 256 KiB | Write, 256 KiB |
| --- | ---: | ---: | ---: | ---: |
| MEM1 K0 | 2217.910 | 923.148 | 1210.837 | 818.331 |
| MEM1 K1 | 71.115 | 231.502 | 71.097 | 231.461 |
| MEM2 K0 | 2217.910 | 919.963 | 1193.495 | 727.802 |
| MEM2 K1 | 19.805 | 231.441 | 19.805 | 231.394 |

Native scalar copy matrix, MiB/s; rows are sources and columns destinations.
Each copy repeatedly visits separate 256 KiB allocations:

| Source → destination | MEM1 K0 | MEM1 K1 | MEM2 K0 | MEM2 K1 |
| --- | ---: | ---: | ---: | ---: |
| MEM1 K0 | 207.243 | 225.810 | 102.586 | 225.989 |
| MEM1 K1 | 67.852 | 48.683 | 66.899 | 48.680 |
| MEM2 K0 | 111.297 | 217.551 | 66.794 | 212.970 |
| MEM2 K1 | 19.536 | 17.550 | 19.416 | 17.528 |

Optimized libc copies and CRC, using cached pointers:

| Operation | MEM1 → MEM1 | MEM1 → MEM2 | MEM2 → MEM1 | MEM2 → MEM2 |
| --- | ---: | ---: | ---: | ---: |
| `memcpy`, final destination flush timed | 201.745 | 101.635 | 106.579 | 66.522 |

| Operation | MEM1 | MEM2 |
| --- | ---: | ---: |
| Cached CRC32 → CPU | 218.549 | 209.172 |

Original hot CPU loops with LC enabled:

| Operation | MEM1 | MEM2 | LC |
| --- | ---: | ---: | ---: |
| Read → CPU, 8 KiB | 2217.910 | 2219.140 | 2221.605 |
| Write from CPU, 8 KiB | 924.108 | 925.069 | 925.819 |

Queue-drained LC DMA, using 8 KiB chunks:

| Direction | MiB/s |
| --- | ---: |
| MEM1 → LC | 1348.845 |
| LC → MEM1 | 1461.454 |
| MEM2 → LC | 439.996 |
| LC → MEM2 | 1465.738 |

DMA timing excludes cache maintenance and verification. It does not establish
an end-to-end processing speedup. Dolphin simulates LC transfers and cannot
supply physical DMA bandwidth; see its
[system-register interpreter](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/PowerPC/Interpreter/Interpreter_SystemRegisters.cpp).

## Benchmark method and safeguards

The [production benchmark](source/Diagnostics/MemoryBench.cpp) is debug-only,
runs only when explicitly requested, and has no idle or release execution.
Its object uses `-O2`; the measured application used default debug `-Og` and
probe level 1. Different build/probe settings must be recorded separately.

| Test group | Working set / method | Rows |
| --- | --- | ---: |
| `memcpy` | Four bank directions; repeated 256 KiB copies | 12 |
| `crc32_cached` | Two banks; repeated 256 KiB inputs | 6 |
| `read32_hot`, `write32_hot` | MEM1/MEM2/LC; repeated 8 KiB loops, LC enabled | 18 |
| `dma_load`, `dma_store` | Both RAM banks ↔ LC; 8 KiB chunks | 12 |
| `copy32_alias` | All 16 bank/alias combinations; separate 256 KiB input/output | 48 |
| `read32_alias_hot`, `write32_alias_hot` | Four aliases; repeated 8 KiB loops | 24 |
| `read32_alias_stream`, `write32_alias_stream` | Four aliases; repeated 256 KiB loops | 24 |
| **Total** | Three repetitions per combination | **144** |

“Stream” means sequential access over that footprint, not a cold-cache pass.
Alias reads have an untimed warm-up. Alias copies use identical volatile scalar
32-bit loops for all modes, avoiding libc cache-specific `dcbz`/prefetch
assumptions. Compare them separately from optimized `memcpy`.

The runner uses only its own 32-byte-aligned allocations and distinct source
patterns per bank. Before alias access it flushes the cached buffers. Timed
alias writes include cached output publication where needed and a final `sync`.
Completed output is invalidated through K0 before CRC/word verification. Cache
operations never target K1, and no allocation is accessed concurrently through
both aliases. Write tests start from zero so unchanged output cannot pass.

LC tests preserve/restore BAT, HID2 and machine-check state, refuse an already
enabled LC, and bound each queue drain to 100 ms. CSV rows are checkpointed
with `fflush` and `fsync` outside timing, retaining completed work after failure.
Timed rows require successful writes, checkpoints and verification; report
close failure marks the run unsuccessful. Buffers are freed before normal application work resumes.

Host ASan/UBSan checks exercise verification, allocation failure, sync failure,
DMA corruption, queue timeout and cleanup. Host aliases cannot model physical
cache behavior. The controller requires every exact operation/alias/block/
repetition combination, rejects duplicate rows, and restores owned SD changes
on success or recoverable failure.

## Coding decisions and next measurements

Use these findings to prioritize changes, then measure the actual pipeline:

- Keep frequently accessed fields contiguous and the active working set small.
  Count input, output, lookup tables and decoder state together.
- Reuse buffers and remove redundant copies. Favor MEM1 for small hot data when
  allocator space permits; use MEM2 for bulk capacity. Cached MEM2 access can
  perform well when the workload stays in cache.
- Treat uncached output as a candidate for a write-only/device-consumed buffer,
  not a general replacement for cached storage. Include later CPU reads, cache
  ownership transitions and device throughput in the comparison.
- Keep cache maintenance at required ownership boundaries, using aligned,
  exclusively owned ranges. Preserve integrity checks and transactional writes.
- Profile instruction footprint before aggressive inlining or loop unrolling.
  Benchmark LC only where its transfer/setup costs and reduced normal cache
  are justified by the processing workload.

Future tests should sweep 8, 16, 32, 64, 128 and 256 KiB working sets, then
512 KiB or larger only when safely allocatable. Separate warm reuse, cold first
passes and sustained access beyond L2; vary buffer placement to test conflict
sensitivity. Compare normal cache against LC enabled, and use validated miss
counters where available. Keep raw kernel timing separate from end-to-end
cache maintenance, I/O and integrity-verification costs. No production tuning
is warranted solely from the current scalar kernels.

## Reproduce and retain evidence

Run host checks and build, then use an isolated Dolphin profile:

```sh
make check
make debug -j4
make release -j4
bash scripts/dolphin.sh --build debug --bench memory --smoke-frames 36000
```

Substitute the printed profile directory for `build/dolphin.PROFILE` below:

```sh
python3 scripts/hbc-smoke.py --profile build/dolphin.PROFILE --memory-bench
python3 scripts/check-dolphin-smoke.py build/dolphin.PROFILE
```

Only after both checks pass, queue that **same frozen DOL** on the shared dev Wii:

```sh
python3 "$HOME/.wii-bench/wiibench.py" add \
  --name wiixplorer-memory-speed --agent wiixplorer-ng --timeout 600 \
  --cwd "$PWD" -- python3 scripts/hbc-smoke.py --hardware --memory-bench \
  --build-dir build/dolphin.PROFILE/artifacts
```

Use the configured shared queue server; never bypass another project's lease.
The controller permits 300 seconds each for memory startup/completion. It saves
frozen binaries, hashes and CSVs under ignored `build/wii.*`, prints medians,
removes owned reports, checks exit and restores settings. For setup and recovery,
see [DEBUGGING.md](DEBUGGING.md). Contributors on their own hardware can pass
`--memory-bench=<new sd:/directory>` to the debug app and retrieve
`memory-capacity.csv`, `memory-benchmark.csv` and `memory-complete` from SD.

### Validation record and resolved defects

| Version | Dolphin profile | Native job / artifacts | Result |
| --- | --- | --- | --- |
| 0.1.4 | `build/dolphin.8yAVUk` | `20261004-105910-ed3057` / `build/wii.bff59o32` | Original 48 operations plus UI/file/exit; restored settings |
| 0.1.5 | `build/dolphin.bL3zzf` | `20261004-135402-86246e` / `build/wii.hmk9lcnb` | All 144 operations plus UI/file/exit; restored settings; 65-second job |

The v0.1.5 run also passed frozen hashes and guest exception/teardown checks;
`make check` and default debug/release builds passed. These artifacts are local,
Git-ignored evidence, not files distributed with the repository.

Earlier retries failed or hung and are not speed evidence. Durable checkpoints
in job `20261004-104839-706391` retained 36 rows and localized a machine check
to the first LC DMA command. DMAL incorrectly stripped the LC tag address
`0xE0000000`; preserving it fixed the failure. The benchmark also preserves
MEM2's physical bit 28 and reads DMAQL with `(HID2 >> 24) & 15`, avoiding the installed
libogc 3.1.0 helper defects. See the
[official assembly](https://github.com/devkitPro/libogc/blob/master/libogc/cache_asm.S),
[queue implementation](https://github.com/devkitPro/libogc/blob/master/libogc/cache.c)
and [libogc2 implementation](https://github.com/extremscorner/libogc2/blob/master/libogc/cache_asm.S).
These workarounds are confined to the debug benchmark; the shared SDK and
release memory behavior remain unchanged. Stale pending/recovery status is
superseded by the successful native runs above.
