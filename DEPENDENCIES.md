# Dependencies and compatibility

The application targets official devkitPro libogc. The installed SDK supplies
libogc, libfat, libdi, tinysmb, wiikeyboard, Wii input/audio libraries, and modern
PowerPC portlibs (zlib, PNG, FreeType, Mini-XML, libmad, Brotli, and bzip2).
FreeType's Brotli/bzip2 transitive dependencies are linked explicitly.

`scripts/build-deps.py` pins every downloaded archive by SHA-256. Source and
compiled archives remain under ignored `.deps/`. It rebuilds with the current
PowerPC compiler and applies tracked patches; it never installs old binaries
into devkitPro. It uses Python's standard library plus curl and patch.

| Ports | Pinned source |
| --- | --- |
| JPEG, TIFF, GD, minizip, 7zip, unrar, MuPDF | [Original WiiXplorer source archive](https://storage.googleapis.com/google-code-archive-source/v2/code.google.com/wiixplorer/source-archive.zip), `branches/libs` |
| NTFS | [libntfs-wii source archive](https://storage.googleapis.com/google-code-archive-source/v2/code.google.com/libntfs-wii/source-archive.zip), `trunk` |
| EXT | [libext2fs-wii source archive](https://storage.googleapis.com/google-code-archive-source/v2/code.google.com/libext2fs-wii/source-archive.zip), `trunk` |
| NFS | [libnfs-wii source archive](https://storage.googleapis.com/google-code-archive-source/v2/code.google.com/libnfs-wii/source-archive.zip), `trunk` |
| Ogg | [Xiph libogg 1.3.6](https://downloads.xiph.org/releases/ogg/libogg-1.3.6.tar.xz) |
| Tremor | [Xiph Tremor](https://gitlab.xiph.org/xiph/tremor), commit `820fb3237ea81af44c9cc468c8b4e20128e3e5ad` |

These snapshots preserve the original app's APIs and feature set; rebuilding
historical libraries does not upgrade their security or file-format support.
Before a release, replace or audit these ports and include their applicable
license texts. The archives contain their original notices and license files;
the build helper does not establish a single license covering all dependencies.

Compatibility patches adapt newlib's opaque devoptab file state, zlib's CRC
types, GC boolean headers, unsupported Wii file locking, and two MuPDF naming
conflicts. EXT is compiled with `-fgnu89-inline` because its headers use that
older inline convention. Dependency recipes are invalidated by compiler version,
script changes, and their patches. Clean dependency work/output after changing
SDK headers or portlibs. Compilation logs are in `.deps/work/<library>/build.log`.

The tracked `data/binary/magic_patcher.o` and embedded booter binaries are
inherited upstream artifacts. No matching magic-patcher source was found in the
archive; that object remains an exception to rebuilding from source. Recovering
its source and documenting binary/asset redistribution rights are release work.

CI uses [devkitPro's official container](https://github.com/devkitPro/docker),
[checkout](https://github.com/actions/checkout), and
[artifact upload](https://github.com/actions/upload-artifact).
A rolling image checks ongoing toolchain compatibility; release reproducibility
also requires pinning that image by digest and recording the package versions,
source checksums, Git revision, build flags, and output hashes.

## HBC-Reborn agent

`scripts/build-hbc-agent.py` pins [HBC-Reborn commit
0c2e3d9f7f8689d9c1dd733ed2d5ec9c6deb70f7](https://github.com/Monsterray/hbc-reborn/tree/0c2e3d9f7f8689d9c1dd733ed2d5ec9c6deb70f7),
archive SHA-256 `52de8dbe2cb4e5d4b181a071c1b80da80a88c51c2042cacd6db1324e0d9f27cb`.
This is upstream master HBC-Reborn 1.10.2, verified on 2026-10-09. The SDK builds with official libogc, `-O2 -g`, and its upstream two-slot transfer
configuration. Source, build and the official host client stay under `.deps/`.
The tracked `scripts/patches/hbc-agent.patch` closes HOME on remote exit and lets a polling exit request return after
the app stops the SDK. Graceful shutdown now uses upstream `hbc_agent_stop()`
instead of the old local shutdown implementation. The SDK rolls back hooks on
failed initialization; the app marks it ready only on success. Stop errors are
reported; physical stop/IOS-stall behavior remains pending validation. The app reserves the SDK's persistent MEM2
netlog/crash/last-log records and joins the listener before unmounting devices. The network/crash
features are enabled in debug builds; the HOME overlay is present in both.
The patch removes `noreturn` from the now-returning exit-request wrapper and
returns from the SDK Reset-button path after a polling app completes teardown.
The patch permits a custom allocator so the SDK does not define duplicate
WiiXplorer bank-routing wrappers; SDK allocation-failure counters do not track
our allocator. WiiXplorer grouped memory probes remain authoritative. Physical
buttons, frame pacing and filesystem cleanup stay owned by WiiXplorer through
the SDK no_safety flags; release also disables SDK stack/thread diagnostics.
The latest official host and queue clients are copied from this same pin,
with its manifest at `.deps/prefix/hbc-agent.json`.

Upstream specifies GPL version 2 or later for the agent and public domain for
`hbc_netlog.h`. Its full GPL text is retained in
`.deps/prefix/licenses/hbc-agent/COPYING`; include applicable source/notices when
redistributing. No HBC keys, channel binaries or WADs are required by this build.

Transfer patches additionally validate NFS reply counts and COMMIT/write
verifiers across a file, correct access flags and bound 32-bit positions.
HBC-Reborn uploads use checked staged replacement and the app's capacity-polled socket guard;
framed downloads retain blocking send mode across frames to reduce IOS overhead.
Accepted agent sockets explicitly enter nonblocking mode before reading request
headers: POSIX/Dolphin accepted sockets do not inherit the listener's mode.
See [TRANSFERS.md](TRANSFERS.md) for limits and measured results.

## ftpsrv server core

Four core files are vendored from ITotalJustice/ftpsrv 1.2.2, commit
`99253bdd62fac99f251f1bf25043afdf3f4b38e7`, under
`source/FTPOperations/ftpsrv`. No platform app, logger or minIni is imported.
Its MIT notices, archive hash and complete local patch are recorded in
[UPSTREAM.md](source/FTPOperations/ftpsrv/UPSTREAM.md). The adapter builds against
official libogc and DeviceHandler. See [FTP.md](FTP.md).

## Archive safety patches

The archive block retains the same pinned upstream snapshots. `zip.patch` now
propagates seek failures and accepts a valid empty ZIP end record at offset zero
while still verifying its signature. `unrar.patch` bounds PPM dictionary requests
and handles failed cleanup allocation. It also replaces incompatible two-entry
Huffman table views with a bounded common base, fixing undefined access found
by the real compressed-RAR sanitizer fixtures. `ntfs.patch` and `ext2fs.patch` add
no-follow `lstat_r` callbacks; normal stat/open behavior is unchanged. These
patches are rebuilt by `make deps` and covered by host regression tests. See
[ARCHIVES.md](ARCHIVES.md) for adapter limits and pending native validation.

`sevenzip.patch` replaces undefined unaligned integer casts in the x86/little-
endian path with standard memcpy loads/stores. The existing bytewise Wii
big-endian path is unchanged. Real pinned SDK fixtures run under ASan/UBSan
when dependency sources and a host `7z` command are available.

The HBC agent local patch also retains queued remote keys while its overlay is
opening/closing, rather than consuming navigation that the UI ignores during
animation. Its upstream pin and public API remain unchanged. Host sanitizer
checks compile the real SDK input queue and portable UI; Dolphin checks both
app callbacks and exit.

## Shared workstation tools

On this workstation, the canonical upstream checkout is
`/Users/monsterray/Agent Folders/hbc-reborn` (1.10.2 at the pin above). The
upstream SDK builds at `sdk/hbc_agent/libhbcagent.a` (libogc) and
`sdk/hbc_agent/libogc2/libhbcagent.a` (libogc2); other Wii apps can use the
upstream documented include/link paths for their matching toolchain. The local
libogc2 build needs `EXTRA_CFLAGS="-I/opt/devkitpro/libogc2/wii/include
-include ogc/libversion.h"` to use the installed layout and select its exception
frame fields (the same approach used by Wii64). This shared SDK is unpatched;
WiiXplorer's allocator/transfer integration stays in its reproducible local pin.

The official `wiibench.py setup` shim at `~/.wii-bench/wiibench.py` follows that
checkout and retains the existing shared queue, history and lease-server setting.
`/usr/local/bin/wiibench.py`, `hbc.py` and `wii-bench-monitor` expose the shared
shim, upstream HBC client and monitor on PATH. Pulling the canonical checkout
updates these tools for every app using them; it does not update an already
running dispatcher or an app's compiled SDK. WiiXplorer validation prefers the
shared shim when present, then its pinned copy for portable contributor setups;
`WII_BENCH_CLIENT` still overrides either. No private server or replacement queue
was created, and no installed Wii channel was changed.
