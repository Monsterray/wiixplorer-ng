# SD and USB storage performance

Research checked 2026-10-03 against the current application, installed official
SDK, and primary sources. Hardware measurements belong below; Dolphin and
network-transfer throughput do not establish physical SD/USB drive speed.

## Hardware measurements

Physical Wii, 2026-10-03, IOS58 revision 6175; devkitPPC r50/GCC 16.1.0,
libogc 3.1.0, debug `-Og`, probe level 3, FTP disabled. These are application
file-I/O speeds, not raw device or Wi-Fi bandwidth. Each result is the median
of three **8 MiB** operations. No CRC errors occurred.

| Mounted drive | Sequential read, 256 KiB | Sequential write, 256 KiB | Same-device copy, 128 KiB | Same-device copy, 256 KiB |
| --- | ---: | ---: | ---: | ---: |
| SD | 7.092 MiB/s | 3.917 MiB/s | 2.146 MiB/s | 2.109 MiB/s |
| USB1, first run | 7.582 MiB/s | 3.102 MiB/s | 1.959 MiB/s | 1.757 MiB/s |
| USB1, interleaved repeat | 7.518 MiB/s | 3.124 MiB/s | 1.950 MiB/s | 1.761 MiB/s |

The interleaved USB repeat starts at 256 KiB and reverses order each round.
128 KiB improved median copy payload throughput by **10.8%** in that repeat
(and 11.5% in the first USB run). SD's 128 KiB result was 1.8% faster in this
sample. The default `CopyFile()` buffer is now **128 KiB**, retaining explicit
16-byte through 256 KiB requests and smaller allocation fallbacks. This saves
128 KiB per ordinary copy versus the prior default. These measurements support
that choice for the attached drives; they do not establish the best buffer for
every drive or cross-device/network workload.

| Mounted drive | Filesystem | Cluster | Logical sector | Partition start | Partition size | Initial free space |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| SD | FAT32 | 32 KiB | 512 B | LBA 8192 / 4 MiB | 7.396 GiB | 703.156 MiB |
| USB1 | FAT32 | 32 KiB | 512 B | LBA 2048 / 1 MiB | 28.651 GiB | 28.645 GiB |

Both report partition type `0x0B`. Both already have 32 KiB clusters and partition
starts aligned to 1 MiB. There is no measured basis to reformat either solely
for cluster size or partition-start alignment. Data-area alignment, hidden flash
erase geometry and file fragmentation were not measured.

The fixture is a deterministic 256 KiB pseudorandom block repeated to 8 MiB.
Generation and CRC verification are outside timed intervals. Writes include
opening/truncating the owned fixture, writing and checked `fclose()`; reads
include open/read-to-EOF/close. Verification rereads the complete file. Copies
use the application's actual staged `CopyFile()` including close and publish,
then verify separately. Small file tests and warm device/cache effects can make
these results optimistic for long sustained transfers. Same-device copy reports
payload throughput: each payload byte requires both a read and a write.

Successful leased jobs `20261003-141146-61a321` (SD) and
`20261003-141606-05e03c` (USB1) retained CSVs, metadata, frozen ELF/DOL/hash manifests,
probes and exit evidence in ignored `build/wii.qhsbdrrt` and
`build/wii.3wsb5d2n`. Both returned to HBC 1.9.3, restored original SD settings,
controls and probes, and removed owned fixtures/reports. CPU/GPU integrity probes
reported no failures. An earlier USB attempt stopped before launch because HBC
rejects WiiXplorer's `usb1:/` alias; the runner now collects USB reports on SD.
It does not time report collection or start FTP. Interleaved repeat job
`20261003-141854-e69d1e` retains the same evidence under `build/wii.ypwyk153`.
The only production performance change is the default buffer; the benchmark
and report collection helpers remain explicit/debug-only.

Reproduce through the shared bench lease after building debug artifacts:

```sh
make debug PROBE_LEVEL=3
python3 "$HOME/.wii-bench/wiibench.py" add \
  --name wiixplorer-storage-speed --agent wiixplorer-ng --timeout 420 \
  --cwd "$PWD" -- python3 scripts/hbc-smoke.py --hardware --storage-device sd
# Repeat with --storage-device usb1 for the mounted USB volume.
```

`--storage-device` supports `sd` and `usb1` through `usb8`; it refuses Dolphin
for physical speed claims. The debug-only application arguments are
`--storage-bench=<new private target directory>` and optionally
`--storage-report=<new private report directory>`. It refuses existing
directories and requires at least 32 MiB free on the target. At most two 8 MiB
fixtures and bounded buffers are live. The completion marker is written after
fixture cleanup; failed I/O/CRC/cleanup fails the runner. Benchmark code is
compiled out of release and never runs without its explicit argument.

## What this build actually uses

`PartitionHandle::Mount()` passes **8 cache pages and 64 sectors per page** to
FAT, NTFS and EXT mounts. At 512-byte sectors this describes 256 KiB of cache
payload, excluding bookkeeping. The FAT SDK installed for this test is
`libfat-ogc 2.1.0-4`, with `libogc 3.1.0-1`: its `fat.h` includes `dvm.h`, and its
`libfat.a` contains FatFs. This is the current **libdvm/FatFs compatibility
implementation**, so performance assumptions from archived libfat should be
retested. Upstream's [build configuration](https://github.com/devkitPro/libdvm/blob/master/CMakeLists.txt)
also names its output `fat`; the [compatibility wrapper](https://github.com/devkitPro/libdvm/blob/master/source/fat_wrappers.c)
passes both cache parameters to `dvmDiscCacheCreate()`.

Current FAT `statvfs()` reports cluster bytes through `f_bsize`/`f_frsize`;
ordinary file `stat.st_blksize` reports sector bytes. Use the former for
allocation-unit metadata. This follows the [current driver](https://github.com/devkitPro/libdvm/blob/master/source/fat_driver.c),
not a guess based on volume capacity.

NTFS and EXT remain historical source snapshots rebuilt with the new compiler;
their archive provenance is in [DEPENDENCIES.md](DEPENDENCIES.md). The EXT port's
`EXT2_LIB_FEATURE_RO_COMPAT_SUPP` does not include modern `metadata_csum`, even
though its headers define that feature. Do not assume an arbitrary newly
formatted ext4 volume is compatible. The NTFS mount enables `NTFS_RECOVER`,
whose port header describes resetting a dirty `$LogFile`; this is not a reason
to accept unclean removal as normal. Local evidence:
`source/DeviceControls/PartitionHandle.cpp`,
`.deps/src/libext2fs-wii/trunk/source/ext2fs.h`, and
`.deps/src/libntfs-wii/trunk/include/ntfs.h`.

USB selection matters: `DeviceHandler::GetUSB0Interface()` uses official libogc
USB storage for IOS <= 200 and the local cIOS USB2 interface for IOS > 200;
`GetUSB1Interface()` exposes the second USB interface only for IOS >= 200.
The latter splits requests into at most **64 sectors** (32 KiB at 512-byte
sectors), and copies MEM1 buffers through a MEM2 scratch area. Larger
application buffers therefore do not mean one equally large USB transaction.
See `source/DeviceControls/DeviceHandler.cpp` and `source/mload/usb2storage.c`.
Do not extrapolate a cIOS-driver optimization to the official IOS path.

## Partition and filesystem choices

| Choice | Recommendation and tradeoff |
| --- | --- |
| FAT32 | First comparison target for SD/USB with this app. Try 32 KiB clusters on a spare volume holding mainly large files, comparing with the measured existing size. Larger clusters reduce cluster boundaries but waste more space for small files. FAT32's per-file ceiling is 4 GiB minus 1 byte. |
| 64 KiB FAT32 clusters | An optional compatibility/performance experiment, not the default. Microsoft lists 64K as a formatting option, but that establishes Windows support, not every Wii app's support. Keep 32 KiB as the conservative starting point and validate all consumers before changing. |
| NTFS | Consider only if single files above the FAT32 ceiling are required and the historical Wii port passes the workload tests. Changing filesystem does not establish a speed gain. |
| EXT | Useful for a controlled Linux-oriented workflow after validating exact features; the old port is a poor default for cross-platform contribution/media interchange. |
| exFAT | Do not select it as a supported WiiXplorer deployment format: this application's partition/mount discovery does not expose an explicit exFAT path. Underlying SDK capability alone does not establish end-to-end support. |
| MBR / GPT | Existing discovery supports MBR, extended partitions, sector-zero FAT volumes and GPT. Prefer a simple MBR layout for a <= 2 TiB/512-byte-sector compatibility test; GPT changes partition metadata rather than the file-data transfer path. Partition records and `AddPartition()` preserve 64-bit starts/counts, but `GetLBAStart()`/`GetSecCount()` return 32-bit values and the installed DISC_INTERFACE uses 32-bit `sec_t`. GPT alone does not establish safe access beyond those paths' address limits. |
| Alignment | Check reported device geometry on a computer. 1 MiB boundaries (LBA 2048 at 512 bytes/sector) are a useful ordinary baseline; flash-specific recommendations can require larger alignment. Partition alignment and FAT data-area/cluster alignment are different. |

The partition-width distinction above is visible in
`source/DeviceControls/PartitionHandle.h` (`PartitionFS`, `AddPartition()` and
the getters). The installed SDK's `ogc/disc_io.h` defines `sec_t` as `uint32_t`;
its sector callbacks consequently accept 32-bit sector addresses/counts.

The FAT32 ceiling comes from [Microsoft's filesystem comparison](https://learn.microsoft.com/en-us/windows/win32/fileio/filesystem-functionality-comparison).
The available allocation-unit options are listed in [Microsoft's format documentation](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/format).
The cluster/batching explanation follows [FatFs's own application note](https://elm-chan.org/fsw/ff/doc/appnote.html):
large aligned requests enable multi-sector I/O, but direct transfers still split
at cluster boundaries. These mechanisms make 32 KiB worth testing; they do not
predict a percentage gain for this Wii or these drives.

[GNU Parted's alignment API documentation](https://www.gnu.org/software/parted/api/group__PedDevice.html)
explains the performance penalty from misalignment to physical sectors;
its [read-only align-check command](https://www.gnu.org/software/parted/manual/html_node/align_002dcheck.html)
checks the selected partition against reported minimum/optimal requirements.
Reported optimal alignment is not proof of alignment to an SD card's hidden
flash erase geometry. The [Parted manual](https://www.gnu.org/software/parted/manual/parted.html)
specifically cautions that 1 MiB can be insufficient for cheap flash media.

SDHC's standard format is FAT32; SDXC's is exFAT, according to the
[SD Association capacity specification](https://www.sdcard.org/developers/sd-standard-overview/capacity-sd-sdhc-sdxc-sduc/).
The Association recommends its formatter for SD-specific parameters and
[warns about nonstandard formatting and portability](https://www.sdcard.org/downloads/formatter/faq/).
For SDXC, that standard formatter's exFAT result conflicts with this app's
current deployment path; do not recommend it blindly as a FAT32 formatter.

## Improvement order

1. Measure existing devices and formats, separately reading, writing and
   copying, with verified temporary files and checked close errors.
2. Compare sector-aligned 32/64/128/256 KiB application buffers. Keep memory
   bounded; the measured copy default is now 128 KiB with smaller fallbacks.
3. If results justify it, A/B-test cache pages/page length and the active
   storage driver's request count/copy overhead. Keep driver changes separate
   from formatting so the cause of a gain is identifiable.
4. On a spare backed-up device, compare current clusters with 32 KiB; then test
   alignment or another filesystem only when that addresses a measured issue.
   Preserve the same drive, fixture, IOS, build and repetitions.
5. Test representative many-small-file workloads too. Sequential throughput
   alone does not measure directory lookup, allocation or fragmentation costs.

No repartitioning or formatting is part of the speed test. A proposed new
layout needs an identified target, verified backup and explicit approval before
it is applied. Present possible gains as hypotheses until an A/B measurement
confirms them.
