# Maintenance review — 2026-10-02

Scope: static review of transfer operations, device/partition handling, HTTP and
update paths, build scripts, task scheduling, and selected archive paths. This is
not an exhaustive security audit. Measured transfer improvements and current
limits are recorded in [TRANSFERS.md](TRANSFERS.md).

## Supplied checklist

| Priority | Item | Result |
| --- | --- | --- |
| P0 | Cross-device move data loss | Fixed: copy skip returns 0; move deletes source only after completed copy. Destination close/flush failure also prevents deletion. |
| P0 | `delete gca` instead of `gcb` | Corrected. Normal unmount helpers already clear these pointers; the erroneous fallback was still unsafe. |
| P0 | NFS unmount index | Fixed to subtract `NFS1`. |
| P0 | NFS bounds | Fixed connection upper bound and mounted-state constant. Also bounded SMB connection indices. |
| P0 | Obsolete self-updater | Removed old download implementation; all public updater entry points fail safely. Removed startup check. Language updates are also disabled because they used the same service. |
| P1 | GPT enumeration | Fixed double increment, final-sector entry limit, and inclusive sector count. Reject unsupported entry sizes and reversed ranges. |
| P1 | Mount null handling | Guarded SD/GC insertion queries, null interface shutdown, negative unmount positions, uninitialized singleton lookup, USB port mapping, and USB mount range. |
| P1 | HTTP/update leaks | Freed read-error/growth-error buffers; safe realloc shrink; deleting obsolete updater also removes its leak paths. |
| P1 | `fread` error handling | `LoadFileToMem` now checks `ferror`. |
| P1 | Unsafe strings | Bounded HTTP request headers and SMB settings copies; bounded HTTP response headers/filename extraction; fixed NFS formatting. Wider audit remains. |
| P1 | SVN revision machinery | Replaced with stable Git version generation, updated credits, and removed numeric SVN auto-fetch from changelog viewing. |
| P1 | README/build/license/provenance | Added build/check instructions and provenance status; current-toolchain build now works; full license inventory and release reproducibility remain open. |

Additional fixes: partial HTTP sends advance the buffer pointer; invalid or
oversized Content-Length fails parsing; download callers preserve signed errors
instead of treating them as huge unsigned file sizes. Resource enumeration no
longer needs GNU `find -printf`.

## Next work, ranked

| Priority | Work | Effort | Evidence / intended behavior |
| --- | --- | --- | --- |
| P0 | Confine archive extraction to destination | Medium | `source/ArchiveOperations/ZipFile.cpp`, `ZipFile::ExtractFile`, joins destination with raw member names. Reject `..`, device prefixes, and paths escaping the root; audit every archive backend and symlink behavior. |
| P0 | Repair ZIP extraction read/write loop | Small | Same function writes `blocksize` rather than `ret`, can keep looping on premature EOF, ignores write/close/CRC errors, and does not check buffer allocation. Write only bytes actually read and report incomplete extraction. |
| P1 | GPT validation and large disks | Medium | `CheckGPT` does not validate CRCs/usable-LBA ranges or reject partial table reads. `GetLBAStart` and `GetSecCount` return u32 while records are u64; formatting/launcher consumers also assume u32. Audit every consumer before widening APIs; refuse formatting unsupported ranges. |
| P1 | Release reproducibility and licensing | Medium | Current SDK build, checksum-pinned historical sources, space-safe paths, and CI workflow are implemented. Validate Linux CI/Windows, pin release SDK/container versions, recover magic-patcher source, and complete asset/binary notices. |
| P1 | Remaining bounds and ownership audit | Medium | Archive item getters, settings imports, fixed paths, and pointer ownership need review. For example `RarFile::GetFileStruct` accepts `ind == size()` before indexing. |
| P2 | Remove obsolete update UI/config | Small | Update controls now show a disabled-service message. Remove dead metadata/icon update toggles, legacy URLs/changelog download code, and obsolete config fields with migration compatibility. |

## Optimization candidates

1. `ProcessTask::ReadDirectory` builds a full recursive file list and updates
   progress per entry. Measure memory and enumeration time on large SD/USB/SMB
   trees; throttle progress updates before replacing the traversal architecture.
   Account for `DT_UNKNOWN` from network drivers and recursion depth.
2. `PartitionHandle::AddPartition` allocates and frees a sector buffer for every
   partition probe. Reuse one aligned buffer if partition scans are measurable;
   keep disk-driver alignment requirements explicit.
3. HTTP metadata reads now allocate only the bounded declared body; streaming
   downloads avoid whole-file memory allocation. Profile real servers before
   extending protocol support.
4. Profile UI/task prompt polling and device discovery on hardware before tuning
   sleeps, priorities, cache sizes, or backend-specific transfer buffers. The default copy buffer is now 256 KiB
   following a CRC-verified SD benchmark; adding caches needs separate evidence.

## Validation and remaining limitations

- `python3 tests/regression.py`: transfer, GPT, and HTTP host checks pass under
  address and undefined-behavior sanitizers. Functions come from production
  source, with filesystem/network/platform stubs; GPT tests use native-endian
  fixtures and do not exercise Wii endian conversion or real disk drivers.
- A clean complete build produces `boot.dol`, `boot.elf`, and `boot.map` with
  devkitPPC r50-1 / GCC 16.1.0 and official libogc 3.1.0-1 on Intel macOS,
  including this checkout's space-containing path. A second unchanged build
  performs no compilation or linking. Legacy warnings remain.
- Missing historical ports rebuild locally from checksum-pinned upstream sources
  with tracked compatibility patches. `magic_patcher.o` remains an inherited
  binary whose source has not been recovered.
- Shell/Python syntax, host regressions (including opaque file-state callbacks),
  `git diff --check`, and representative Git ignore checks pass.
- Dolphin 2606a launches with an isolated profile and frozen matching debug
  artifacts. Boot logs show executable loading and Wii-memory setup; menu,
  input, audio, and file operations have not been verified.
- CI is configured but has not run remotely. Native Linux/Windows builds and
  full physical Wii scenarios remain unverified; see [DEBUGGING.md](DEBUGGING.md).

The current compiler also exposes existing warnings worth prioritizing:
`PartitionFormatter.cpp` reads beyond the volume-label literal;
`ProcessChoice.cpp` uses destination-sized `strncat` bounds; FTP and settings
formatting can overflow fixed buffers. Review and test these before enabling
formatting or broad untrusted-input scenarios. These findings are not repaired
by getting the application to compile.

Before release, test individual/all-file skip, overwrite, cancellation,
read/write failures, full media, empty files, recursive moves with retained
files, missing USB port 0 with port 1 present, every NFS index, unmount/shutdown,
and multi-sector GPT tables on a Wii. Null guards do not solve concurrent hotplug
lifetime races. Install updates manually until authenticated release delivery
is designed and tested.


## CPU/GPU and exit follow-up

The build now has separate debug/release outputs and optional grouped probes.
A deterministic host test reproduces the old task-queue lost wakeup; current
queue/CMutex tests cover concurrent producers and shutdown. An invalid mutex
unlock in the old destructor was confirmed in Dolphin GDB as an interrupt-disabled
infinite loop and fixed. Exit requests now unwind callbacks before cleanup, with
workers joined and GPU/audio producers stopped before resources are released.
FAT volumes without an MBR now mount (including Dolphin's default SD image).

The default Metal backend on the tested Intel Mac intermittently lost textured
sprites. OpenGL passed the same idle frame check and is the Mac test default.
This does not establish physical Wii rendering stability or every workload's
thread safety. Remaining work includes worker/UI completion ownership throughout
nested GUI elements, active copy/FTP/audio shutdown scenarios, GDB breakpoint
behavior in the installed Dolphin build, controller-driven end-to-end tests,
and hardware checks under the central Wii lease. Keep full/control/full probe
runs when estimating instrumentation overhead. See DEBUGGING.md for evidence.

## HBC-Reborn integration

The old HOME menu is replaced by the pinned HBC-Reborn SDK overlay. Settings
and Diagnostics occupy its two app slots; network/crash features run in debug.
MEM2 allocations preserve the SDK record gap, and the listener joins before
devices unmount. Failed settings/control saves no longer close NULL streams and
now propagate write/close errors. SDK source/client builds are independent of
local sibling checkouts.

Dolphin and a queued physical Wii smoke passed HOME, both app buttons, remote
screenshots/input, SD file roundtrip, heavy integrity probes and HBC return.
The hardware runner backs up/restores SD files, disables temp deletion and
checks the shared lease. Release HOME, DEV remote calibration/speaker actions,
new crash capture/symbolization, active-transfer interruption, and whole-app
restart remain scenario-specific follow-up work. See DEBUGGING.md for evidence.

## Transfer follow-up

Completed: checked staged replacement for copies, moves, HTTP and FTP/HBC
uploads; bounded memory downloads and socket waits; no infinite zero-byte I/O
loops; checked FTP final completion; capped NFS payload/count parsing and
file-wide write-verifier/COMMIT validation. The copy buffer increased from
70 KiB to 256 KiB after CRC-verified physical SD measurements (about 18% gain).
Native sends now poll a configured low-water mark before writing: a shutdown
watchdog failed to bound an actual stalled Wii download, and nonblocking IOS
sends failed checksum validation. Capacity polling passed both tests; network
throughput must be measured with that policy. Limits, recovery and measurements are in
[TRANSFERS.md](TRANSFERS.md).

Directory planning now bounds entries, path memory and recursion, and keeps only
one directory stream open rather than accumulating FTP listing buffers at every
depth. Copies and cross-device moves preserve empty directories. Planning and
creation failures retain the source and reject the incomplete plan.
The HBC networking comparison is in [HBC-NETWORKING.md](HBC-NETWORKING.md);
native send bounds remain a requirement alongside throughput measurements.

A forced early-thread-start host test reproduced a pure virtual call in the old
CThread constructor handshake. The entry now suspends itself without reading
the unpublished handle or calling a virtual method during construction.
Dolphin hardware breakpoints caught a DSI in GuiFrame::Draw during the shutdown
fade after owners had been deleted. Teardown no longer redraws the destroyed
scene. The full FTP transfer/idle-abort/active-upload-exit Dolphin test passed
after that fix, with zero CPU/GPU integrity failures.

The first ftpsrv modernization block passed native SD and USB1 transfers,
idle preservation and app exit, plus host lifecycle/authentication/teardown
checks. Disabled FTP has no worker, sockets or session arena. The retained ftpii
backend remains available for comparison. See [FTP.md](FTP.md) for the pinned
core, local patches and validation.

Remaining: repeated native FTP UI enable/disable and sustained multi-client
load checks, legacy FTP startup reliability, real SMB/NFS server
benchmarks, archive extraction bounds/confinement, malicious remote metadata
parsing, storage-driver blocking and concurrent hotplug lifetime races. Do not
interpret transfer failure checks as a complete filesystem security audit.
