# Archive safety and validation

Version 0.1.1 retains the pinned minizip, 7zip SDK and unrar libraries. The audit
confirmed the reported ZIP incorrect byte counts/EOF handling, repeated recursive
packing, unchecked writes/closes/CRC, 7z decoded-slice and index errors, RAR
pre-extraction deletion and size truncation, Wii archive index/range errors,
and unsafe U8/RARC and LZ77/Yaz0 parsing. These paths now share checked extraction
paths and staged output. No archive worker, poll loop or idle allocation was added.

## Destination and replacement behavior

`ArchiveSafety` validates every member, including the full name when extracting
only its basename. It rejects absolute paths, device prefixes, backslashes,
`.`/`..`, controls, empty components, trailing dots/spaces (FAT aliases), and
unsupported links/special entries. Every joined destination is checked. Ancestors
and existing targets are checked without following links. FAT is explicitly
identified before using stat in place of lstat; NTFS/EXT receive no-follow
callbacks through tracked dependency patches. Filesystems without a trustworthy
no-follow callback fail closed. This can restrict extraction to network mounts.

Each output uses the existing `wx_transfer_*` sibling staging/recovery mechanism.
Only a complete payload with successful backend CRC and file close is published.
Failures and cancellation preserve the original; abort follows the existing
recovery policy, retaining an original in `previous` if rollback fails. ZIP
creation and append stage the entire archive and require successful member and
archive closes before publication. App shutdown also cancels these operations.

Extract All is transactional **per file**, not for the entire directory tree:
completed earlier files and created directories remain if a later member fails.
Preflight validates every member, sums declared payload sizes with overflow
checks and queries destination free space. This is an estimate, not a space
reservation; allocation overhead and concurrent writers can still cause checked
write failures. It does not delete originals to make room. Power-loss durability
and hostile concurrent filesystem mutation are not guaranteed by pathname checks
or by the inherited rename/recovery mechanism. Avoid changing the destination
through FTP or another writer while extracting.

## Resource and compatibility limits

| Guard | Reason |
| --- | --- |
| 767-byte joined path, 255-byte components, 32 member components/recursion levels | Bound path buffers, parser recursion and open-directory stack; reject truncation and pathological trees. A staging suffix may cause a filesystem to reject a maximum-length basename safely. |
| 32,768 entries (including synthetic ZIP directories); RAR at most 131,072 scanned headers | Bound metadata and parser work. |
| 8 MiB metadata ceiling, reduced when less heap is available | Prevent untrusted item/name tables exhausting Wii RAM. |
| Decoder budget at most 16 MiB and at most half currently free MEM1/MEM2 application heaps | Leave application headroom. Both 7z allocator contexts share a tracked aggregate budget. A solid block larger than the budget fails cleanly. |
| RAR PPM dictionary at most 16 MiB and within the available-memory budget; compressed members require 8 MiB headroom | Bound SDK dictionary allocation and leave space beyond the 4 MiB unpack window. Stored RAR members use a reused 64 KiB buffer. This is not a global allocator quota for every internal unrar allocation. |
| Whole-buffer LZ77/Yaz0 and compressed U8/RARC inputs/outputs checked against available-memory budget | These formats require resident buffers; no untrusted declared size is allocated unchecked. |

Metadata payload and compressed lengths are 64-bit. Streaming 7z/RAR outputs
are rejected when the destination's `off_t`/filesystem cannot represent them;
FAT files cannot exceed 4 GiB minus one byte. No arbitrary small streaming-file
limit was added. The historical archive input APIs use `fseek(long)` on Wii:
ZIP, 7z and RAR compressed archive inputs are limited to the signed 32-bit seek
range. Classic minizip also limits creation/append to below that range, using a
conservative compression bound before writing. ZIP64 metadata is explicitly
rejected rather than truncated. Upgrading these backend APIs is future work.

Dependent solid RAR members and split-volume members fail closed: the inherited
per-member decoder does not reconstruct preceding dictionary or volume state.
7z solid blocks are supported within budget and cached only for the current
extraction. Cancellation is checked before and after the SDK decode and during
output writes; the SDK does not offer cancellation within a single decode call.

## Performance changes

ZIP packing walks one bounded directory stack, preserves exact relative paths
and empty directories, and visits each entry once. PackTask no longer constructs
a whole recursive transfer plan before walking again. Traversal stat results are
reused; opened regular files are checked again for size/type changes. Compression
uses one buffer across files. Extract All reuses streaming buffers; 7z reuses
its decoded solid block and RAR stored members reuse their I/O buffer. All such
buffers are released at operation end. Progress updates are throttled to roughly
256 KiB of work, plus completion updates. Existing ZIP/Wii streaming capacities
and compression defaults are unchanged; no throughput improvement is claimed
without native measurements. Safe ZIP append copies the original archive once
and staged replacement needs temporary space.

## Verification

Run `make check` with a host C/C++ compiler. The archive suites use ASan/UBSan:

- `tests/archives.py` compiles production path/staging helpers, archive adapters,
  parser and decompressor functions with platform/codec fault-injection stubs.
  It covers traversal, links, lengths/depth, exact ZIP trees and empty entries,
  short/zero/error reads, write/close/CRC failures, cancellation preserving
  originals, 7z nonzero offsets/budgets/indices, malformed overlapping LZ streams,
  corrupt U8/RARC offsets/counts/cycles and preserved 64-bit metadata.
- `tests/archive_fs.py` exercises the production NTFS/EXT patch callbacks with
  inode/volume stubs, including no-follow behavior, errors and lock cleanup.
- `tests/archive_codecs.py` additionally compiles the pinned minizip sources after
  `make deps`. Real ZIP fixtures exercise CRC failure, damaged/truncated input,
  unsafe names/links, empty archives/directories, exact created trees and staged
  append. Without dependency sources it explicitly skips this optional suite.
  The always-run adapter tests still cover fault injection.

The v0.1.1 full host checks, debug build (`PROBE_LEVEL=3`) and release build
passed locally with devkitPPC r50 / GCC 16.1 and official libogc 3.1.0.
The subsequent v0.1.2 native SD fixture run passed as recorded below. Native
NTFS/EXT behavior, cancellation/shutdown under load, encrypted/split archives,
and power-loss tests remain validation work. Fuzzing the legacy codecs
and modernizing their seek APIs are useful next steps.

## Native fixture runner

`make debug PROBE_LEVEL=3` includes `--archive-check=DEVICE:/wiixplorer-archive-NAME`.
The release build excludes this entry point. `scripts/archive-fixtures.py` uses
Python's standard library and a host `7z` executable to generate deterministic
ZIP/7z/stored-RAR/U8/RARC/LZ77/Yaz0 fixtures. Valid cases verify bytes/CRC and
metadata counts; malformed/traversal/CRC/budget cases must preserve a seeded
original target. The runner also creates/extracts an exact ZIP tree including
an empty directory. The hardware controller verifies empty files/directories
and keeps timing/results under ignored `build/wii.*`.

Queue `python3 scripts/hbc-smoke.py --hardware --archive-device sd --capture-log`
through the shared lease described in DEBUGGING.md; repeat with `usb1` when a
USB test partition is mounted. Only isolated fixture directories are written.
The controller backs up/restores settings and removes its known fixtures; it
refuses to delete unknown leftovers. Expected decoder error dialogs are
acknowledged only during this explicit fixture run. No repartitioning or
formatting is part of these tests. Native short-write/close fault injection and power-loss/concurrent-write tests
are not covered by this runner; retain the host fault tests and the pending validation list.

`tests/native_archive_bench.py` runs the production native runner with real
pinned minizip under ASan/UBSan, including CRC failure preserving the original,
exact packing, manifest guards and completion reporting. It requires `make deps`.

The baseline native run on 2026-10-04 (`build/wii.kmr54g_s`, job
`20261004-013028-61678c`) passed HOME/settings/diagnostics, the agent file
roundtrip, level-3 CPU/GPU integrity checks, and clean return to HBC. The
runner measured 6.977 seconds from requesting exit through its final report
collection (not pure teardown time) and restored all saved settings. This
baseline does not establish archive codec correctness or absence of visual
flashing under every workload.

The optional `tests/archive_seven_codec.py` also links the real pinned SDK
against the production 7z adapter (ASCII filename platform shim). It validates
solid members with nonzero offsets, empty entries, invalid indices, corrupt
packed data preserving originals and aggregate decoder budget rejection.
ASan/UBSan findings fail the run. A small host-endian SDK patch removes the
unaligned integer casts found by that test; Wii's bytewise path is unchanged.

Two pinned libarchive compressed-RAR fixtures also cover normal and best
compression through an independent first member. The best fixture requests a 25 MiB PPM
dictionary and must fail within the 16 MiB budget while preserving the original. Source notices/hashes and the
explicit fixture transformation are in
[tests/fixtures/rar/UPSTREAM.md](tests/fixtures/rar/UPSTREAM.md). Stored RAR is
locally generated; this extends the runner to real compressed RAR without
replacing the backend. Encrypted, dependent-solid and split-volume compatibility
still require separate coverage.

Real RAR codec regression testing also found/fixed signature positioning on
rewind and rejection of corrupt main headers. The historical decoder cast
several differently sized Huffman structs through a two-element array view;
tracked patches now use one bounded base table with genuine derived types.
This adds a few KiB to decoder state (4,960 bytes on the tested 64-bit host). That state now uses checked heap
allocation rather than exceeding a typical Wii worker stack. Decoder memory
and its 4 MiB window are released together at operation completion.
`tests/archive_rar_codec.py` compiles the pinned decoder plus production adapter
and error handling under strict ASan/UBSan: stored/normal payloads succeed; bad
CRC/main header and oversized PPM dictionary preserve existing targets.

## Physical Wii results, 2026-10-04

Job `20261004-023054-307041` passed all **30** SD cases plus normal HOME,
settings/diagnostics, file roundtrip and return to HBC. Settings/controls/probes
were restored and owned fixtures removed. Results are retained in ignored
`build/wii.3szw21i8/archive-results.csv`. This tested the frozen debug DOL
SHA-256 `d8a98e04edaece3eaa885d5827fa39a7196b687119a819b3e590439273ce8dff`.
ZIP/7z/RAR, both Wii containers, both compression wrappers, empty directories,
CRC failures, budget rejection and seeded-original preservation all passed.
The first run exposed incorrect RARC fixture root/count and cycle-entry
expectations; those fixtures were corrected, without changing parser behavior.

USB setup failed before app launch: HBC does not expose `usb1:/`, and a later
request to its `usb:/` service timed out and left HBC unresponsive. USB archive
validation is therefore **not passed**. Settings restoration is queued as
`20261004-023553-772e84`. The corrected runner stages all fixture transport on
SD; an explicit `--archive-output=usb1:/wiixplorer-archive-NAME` makes WiiXplorer
copy/read/extract/pack on its own USB mount. Native checks validate zero-length
files and directories, then remove only known fixture files and empty parents.
Unknown recovery files are retained; HBC never accesses USB for this run.
Report transport remains on SD. This path also passes the real ZIP host harness.

The latest frozen debug candidate is `build/native-validation-instrumented-0.1.2`,
DOL SHA-256 `e5d3decbd877ceb4523e5321cf300f94460fe13e10e7e1a86ee42782350f6ab4`.
USB rerun `20261004-024108-6116ba` awaits HBC recovery. These fixture helpers
are entirely excluded from release, with no idle archive work. Full `make check`
(including actual pinned 7z/RAR codecs under strict ASan/UBSan), debug with
level-3 probes and release builds all passed locally. The host SDK alignment
patch does not change Wii decoding. No archive buffer or compression defaults
were changed. The debug fixture manifest is capped at 64 cases; this does not
change production archive limits. The first failed RARC fixture run retained
its unexpected generated root entry under `sd:/wiixplorer-archive-wii.vy12t8l5`;
unknown leftovers were intentionally not recursively deleted.

## Dolphin-first follow-up, 0.1.3

All 30 production archive cases passed in Dolphin (`build/dolphin.p9VRp8`),
with Settings/Diagnostics, file roundtrip and completed guest/core shutdown.
Frozen hashes, exception logs and CPU/GPU integrity checks passed. The original
USB retry was canceled until these checks completed. Settings recovery
`20261004-023553-772e84` completed at 08:22.

Physical USB jobs `20261004-090010-c28017` and `20261004-090539-ebee94` passed
all 29 extraction fixtures. Packing produced four valid entries, correct payload
CRC and an empty directory, but debug cleanup reported EACCES while pruning a
nonempty parent. Reports now record the failing phase and cleanup errno. The
cleaner checks occupancy on EACCES, reading at most three entries (dot, dot-dot,
first child), then stops pruning. Real denial on an empty directory and read/close
failures still fail; unknown content remains untouched.

The host regression reproduced the failure before the fix and passed afterward,
including real empty-parent denial. All 30 cases passed again in Dolphin
(`build/dolphin.Pu4bol`) before job `20261004-091300-812e6b` passed all 30 on
physical USB1. It also passed UI/file/exit, returned to HBC and restored original
settings/probes. Accepted native artifacts are in `build/wii.xv7iohmp`. Earlier
failed fixture roots and failure artifacts (`build/wii.kkoex1pp`,
`build/wii.oppwkt0t`) remain retained; no recursive deletion of unknown/recovery
content was performed. This fix changes only debug fixture cleanup, with no
production archive or storage-driver changes and no idle release overhead.
