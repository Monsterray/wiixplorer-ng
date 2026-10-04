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
Real 7z/RAR decoder runtime validation, native 32-bit boundary fixtures, SD/USB
FAT/NTFS/EXT behavior, cancellation/shutdown under load, low-memory solid blocks,
and performance measurements remain physical-Wii validation work. The bench Wii
is unavailable; no native archive result is claimed. Fuzzing the legacy codecs
and modernizing their seek APIs are useful next steps.
