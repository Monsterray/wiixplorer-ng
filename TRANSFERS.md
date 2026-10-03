# Transfers

WiiXplorer streams transfers through bounded buffers. Local copies use a
32-byte-aligned 256 KiB buffer, falling back to 128/64/32 KiB if allocation
fails. This default comes from a real SD-card comparison, rather than an
assumption that larger allocations are always faster.

## Replacement and completion

Copy, HTTP download, FTP-server upload and HBC-agent upload create a private
`destination.wx-transfer-N` directory on the destination filesystem. Data goes
into `data`; the original destination remains available until the transfer has
completed and its file has closed successfully. Replacement moves the original
to `previous`, publishes the completed file, and removes the backup. Failure to
publish attempts to restore the original. A failed rollback retains `previous`
for manual recovery. Never delete a recovery directory without inspecting it.

Empty directories are preserved during copies and cross-device moves. A move
removes an empty source directory only after creating its destination.
Directory creation rejects existing regular files and excessively long/deep
paths. Planning errors discard the incomplete selection before file transfers;
a selection over the budget must be split into smaller jobs.

There are at most 16 reservation attempts per destination. Paths are bounded;
no existing reservation is reused or truncated. Same-device moves use the same
replacement procedure. Cross-device moves remove their source only after a
successful copy; skip, cancellation, read/write and close errors retain it.

This handles reported I/O failures. FAT and remote filesystems require two
renames, so replacement is **not power-loss atomic**. An interrupted replacement
may leave the original in `previous`. A completed `fclose` is the backend's
completion contract; it cannot guarantee that every device has physically
flushed its cache. Concurrent edits to a source or destination are unsupported.
Allow room for the staged file and the existing destination.

## Limits

| Path | Working memory / size bound | Deadline / completion checks |
| --- | --- | --- |
| Directory planning | 32768 charged paths/items; 4 MiB conservative path/node budget; 64 directory levels; paths below 1024 bytes; one open directory stream | Checks every directory read/stat/close; closes parents before descending; cancellation between entries; errors discard the partial plan |
| File copy | 256 KiB, allocation fallback to 32 KiB; streams stat-reported length | Exact reads/writes, source growth check, checked closes, cancellation between chunks |
| Shared network I/O | 4 KiB sends, 16 KiB receives; write batches capped at 256 KiB; no extra worker/heap buffer | 10 s receive/idle-send deadline; 120 s total write-batch deadline; poll for enough native send capacity; app exit cancels |
| HTTP | 4 KiB headers; 16 KiB receive blocks; Content-Length at most INT32_MAX | 10 s header deadline; 1 h body deadline; exact declared length; checked file close |
| HTTP in memory | 16 MiB ordinary downloads; 4 MiB metadata | Same strict framing; unsupported transfer encodings fail |
| General memory file load | 32 MiB | Rejects size narrowing and failed reads/closes |
| FTP server (ftpsrv default) | 4 sessions; shared 32 KiB buffer; native 4 KiB sends / 16 KiB receives; uploads at most 8 GiB; REST at most LONG_MAX | Configurable session idle timeout (300 s default); 4 h transfer/listing deadline; checked writes/closes and staged replacement; no arena/thread/sockets while disabled |
| FTP client | 4 KiB send / 16 KiB receive calls; bounded command/path buffers; 4096 listing entries (about 1.1 MiB per list/cache) | 10 s reply deadline, at most 64 reply lines; 60 s directory-list deadline; exact requested reads; final upload reply must be 226/250 |
| HBC-Reborn files | 512 MiB per file; existing two-slot 64 KiB frame pipeline | 600 s request deadline, bounded socket waits; framed CRC validation; checked file close |
| NFS | Legacy 32-bit file positions; rejects files/operations beyond UINT32_MAX; write/read payloads at most 3840/8064 bytes | Finite UDP retries; reply count/payload bounds; persistent write verifier checked through COMMIT |

Native IOS can falsely report nonblocking sends as complete. The app instead
sets `SO_SNDLOWAT` to its send-block size, polls for that capacity and sends
blocking. Increasing the block size to 16 KiB passed real-Wii checksums and
stalled-peer recovery but reduced throughput; the default is 4 KiB. An IOS
failure to configure the low-water mark fails the transfer. Dolphin hosts that
reject this option use correct nonblocking host-socket semantics, only after
verifying the emulator-only `/dev/dolphin` device. The socket's original mode
is restored after every write batch. Concurrent writes to one socket are
unsupported; each existing transfer owns its connection.

Deadlines bound the app's network loops. Filesystem driver calls may block
internally; these changes do not claim a hard real-time bound on storage or the
SDK's SMB implementation. DNS and remote metadata parsing also require further
audit. Use trusted FTP/NFS/SMB servers. HTTP has no TLS support; these limits do
not authenticate downloaded content.

The retained ftpii comparison build keeps its older limits. [FTP.md](FTP.md)
records the new server lifecycle and [upstream modifications](source/FTPOperations/ftpsrv/UPSTREAM.md).

FTP data connections must match the authenticated control peer; third-party
active targets are rejected. Accepted upload files are capped at 8 GiB; a
rejected staged upload can transiently exceed that by one 16 KiB receive block.

FTP has no declared upload length or mandatory checksum: orderly data EOF is
completion even if the sender intended more bytes. Use HBC-Reborn's framed,
CRC-checked protocol when a verified upload is required. Raw HBC compatibility
uploads do not provide the framed protocol's checksum protection.

## Measurements and repeatable checks

An 8 MiB on-device SD fixture was copied three times per buffer size. Every
result was read back and CRC-checked. Debug build, devkitPPC r50-1, libogc 3.1.0,
physical development Wii, 2026-10-02:

| Buffer | Median MiB/s |
| --- | ---: |
| 32 KiB | 1.938 |
| 64 KiB | 1.901 |
| Previous 70 KiB | 1.817 |
| 128 KiB | 2.073 |
| New 256 KiB | 2.143 |

The new default improved this SD workload by approximately **18%**. Other cards,
USB devices, network servers and release builds may differ. The benchmark times
the copy itself; fixture creation and CRC readback are outside the timed region.

Run host failure tests with `make check`. They exercise production code with
filesystem/socket stubs under address/undefined-behavior sanitizers: short/zero
I/O, failed close/replacement, cancellation, malformed HTTP framing, FTP final
reply failure and NFS server-verifier changes. They supplement hardware tests.

Debug-only physical tests must use the shared bench queue described in
[DEBUGGING.md](DEBUGGING.md):

```sh
python3 "$HOME/.wii-bench/wiibench.py" add \
  --name wiixplorer-transfers --agent wiixplorer-ng --timeout 420 --cwd "$PWD" -- \
  python3 scripts/hbc-smoke.py --hardware --copy-bench --transfer-bench
```

`--transfer-bench` measures three 8 MiB upload/download repetitions for random
and compressible data and checks CRC, truncated, idle and oversized-upload
failures retain the original. It also leaves a download peer connected without
reading and requires the listener to recover within 20 seconds on hardware
(60 wall-clock seconds in Dolphin, where emulated time can run slower). Upload
rejection must come from the app; a client-side timeout fails the test. Use
`--transfer-mib 1 --transfer-repeats 1` for a shorter diagnostic fixture. `--ftp-smoke` separately checks authenticated
roundtrip, empty files, resume, append, idle abort and app exit during upload.
`--capture-log` captures debug startup output on port 4300 when HBC has no
existing log target. Artifacts and matching binaries stay in ignored `build/`.
Physical Wi-Fi medians from three verified 8 MiB transfers:

| Data / direction | Earlier SDK baseline MiB/s | Staging + former shutdown watchdog MiB/s |
| --- | ---: | ---: |
| Random upload | 0.840 | 0.849 |
| Random download | 0.537 | 0.535 |
| Compressible upload | 3.599 | 3.377 |
| Compressible download | 4.359 | 4.358 |

Staging and checked replacement add metadata work. These earlier measurements
show the cost of staging; they do not establish a network speedup or a stalled
send bound. The shutdown watchdog later failed a real-Wii stalled-peer test and
was replaced with capacity polling. A 16 KiB polled-send trial passed checksums,
CRC/short/idle/oversize rejection and recovery while the download peer remained
open; its random download median was 0.180 MiB/s and compressed download was
3.289 MiB/s. A separate 4 KiB polled-send trial, with a 10-second total batch
deadline, passed three 8 MiB repetitions and stalled-peer recovery:

| Data / direction | 4 KiB capacity polling MiB/s |
| --- | ---: |
| Random upload | 0.871 |
| Random download | 0.140 |
| Compressible upload | 3.423 |
| Compressible download | 3.245 |

These are separate trials, not an interleaved A/B comparison. The lower native
download throughput is a material cost of the capacity gate. Subsequent
screenshots exposed healthy slow progress exceeding the old total deadline;
the final policy uses 10 seconds without progress and a 120-second total batch
cap. It passed native CRC/short/idle/oversize rejection, stalled-peer recovery,
HOME/exit and SD restoration. Its shorter 1 MiB single-run rates were random
up/down 0.354/0.057 and compressible up/down 2.721/2.259 MiB/s, demonstrating
why individual Wi-Fi runs cannot establish a speed improvement.

[HBC-NETWORKING.md](HBC-NETWORKING.md) records HBC-Reborn's pipeline,
compression and interleaved benchmark research. Its SDK already supplies our
bounded frame pipeline and adaptive compression. Increasing the native send
block or adding socket options requires both integrity and stalled-peer tests;
HBC's ordinary blocking send loop does not establish a stalled-write bound.
Actual SMB/NFS server benchmarks remain future work. Archive extraction and
remote metadata parsers need separate security work; see [REVIEW.md](REVIEW.md).

## Storage follow-up (2026-10-03)

Native SD/USB read, write and staged-copy benchmarks are recorded in
[STORAGE.md](STORAGE.md). Interleaved USB tests found 128 KiB copy buffers about
11% faster than 256 KiB on the attached drive; SD was similar/slightly faster
at 128 KiB. The default `CopyFile()` buffer is therefore 128 KiB, with explicit
requests up to 256 KiB still supported. Historical 256 KiB results above describe
the earlier build, not the current default. Partition/cluster recommendations
and the leased `--storage-device` runner are documented in that storage report.
