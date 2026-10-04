# Debugging and runtime testing

Research date: 2026-10-02. The following workflow adapts the local Wii64 project;
it separates observed build/launch results from the remaining functional tests.
Build success, Dolphin boot, controller/file-operation checks, and physical Wii
checks are separate results.

## Toolchain and local tools

Read-only inspection found devkitPPC `r50-1` (GCC `16.1.0`), official libogc
`3.1.0-1`, and Dolphin `2606a` installed on this Intel Mac. devkitPro lives at
`/opt/devkitpro`. `powerpc-eabi-gdb`, `powerpc-eabi-addr2line`, and
`powerpc-eabi-objdump` are in `devkitPPC/bin`; `elf2dol` and `wiiload` are in
`tools/bin`. These are local observations, not universal version requirements.

Use devkitPro's package-managed Wii toolchain and the library paths selected by
this project's build. The sibling Wii64 uses Extrems' **libogc2**, which is a
separate fork installed here at `/opt/devkitpro/libogc2/wii/include` and
`/opt/devkitpro/libogc2/wii/lib`. Do not silently substitute that fork for
official libogc or mix archives compiled with different toolchains.
Sources: [devkitPro setup](https://devkitpro.org/wiki/Getting_Started/devkitPPC),
[official libogc](https://github.com/devkitPro/libogc),
[libogc2 upstream](https://github.com/extremscorner/libogc2),
[Wii64 Mac setup](../Wii64/doc/macos-development-setup.md).

Keep the exact `boot.dol`, `boot.elf`, `boot.map`, Git revision, compiler/package
versions, and any nondefault build flags together for each run. Hash the DOL
and ELF before launching. A rebuilt ELF can resolve a crash to the wrong line.
The current Makefile retains debug information while optimizing at `-O2`;
inlined functions and optimized variables can complicate source stepping.
The separate `-Og -g3` debug build is useful after a failure is reproduced,
but first reproduce with the ordinary build.

## Dolphin: isolated interactive boot

Use a fresh absolute user-folder path for each run. Copy only the controller
mapping needed for testing; do not copy the user's normal NAND or SD files.
Dolphin supports `-u` for a user folder, `-e` for a boot file, `-d` for the
debugger, and `-C System.Section.Key=Value` for per-run configuration.
[Dolphin command-line implementation](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/UICommon/CommandLineParse.cpp).

From the project root after building:

```bash
bash scripts/dolphin.sh                # create isolated profile and launch
bash scripts/dolphin.sh --debug        # also open Dolphin's debugger
bash scripts/dolphin.sh --prepare-only # create fixtures/artifacts without launching
```

The helper uses Launch Services with `/Applications/Dolphin.app` on macOS
(override `DOLPHIN_APP` for another location) and `dolphin-emu` elsewhere. Set
`DOLPHIN_EXE` to an installed executable on Linux/Windows when needed; Windows
paths are converted by the devkitPro shell's `cygpath`. Override
`DOLPHIN_WIIMOTE_CONFIG` to copy a particular controller mapping. Each run keeps
its frozen build, SHA-256 hashes, test SD folder, and logs in an ignored
`build/dolphin.*` directory. The helper enables MMU, IOS58, single-core emulation,
SD writes/folder sync, and file logging through ordinary Dolphin CLI options.

The SD folder must be prepared **before boot**. WiiXplorer looks for settings in
`sd:/apps/WiiXplorer/WiiXplorer.cfg` regardless of the NG package directory.
Its default boot IOS is 58; forcing the emulator's initial IOS to match reduces
an unnecessary reload while establishing the first boot. Later test the reload
path separately. These are derived from `source/Settings.cpp` and
`source/Controls/Application.cpp`, not a verified workaround for every boot
issue. Dolphin's current settings define MMU, boot-IOS override, SD writes and
folder sync. [Dolphin settings source](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/Config/MainSettings.cpp).

On this Mac, Wii64 uses `open` through Launch Services because launching the
executable directly from an agent shell previously aborted in Cocoa setup.
Wii64 copies its mouse/Wii Remote bindings from the normal profile. Confirm an
emulated Wii Remote 1 is connected; a visible menu alone does not prove input
works. Do not inherit Wii64's ROM chains or AESND-specific DSP LLE requirement:
WiiXplorer needs its own audio check. If there is a black screen, check the live
display and try immediate XFB in this profile before concluding rendering is
broken. Source: [Wii64 Dolphin helper](../Wii64/.dev/dolphin_test.sh).

Close this instance normally before checking SD sync output. Preserve any
`WiiSDSync.xxx` recovery directory rather than deleting it. Logs, profiles,
screenshots, fixtures, and generated SD images belong outside Git. Never stop
another project's Dolphin process; identify this instance by its profile path.

## Minimum functional test matrix

| Check | Pass evidence | Platform |
| --- | --- | --- |
| Clean boot, empty/new configuration | Menu visible, SD listed, no guest fault | Dolphin, Wii |
| Wii Remote pointer and A/B/HOME | Pointer moves, expected actions, clean exit | Dolphin, Wii |
| Settings save and reload | Selected setting persists across two boots | Dolphin, Wii |
| Browse/copy/rename/delete test files | Expected names and byte hashes after shutdown | Dolphin, Wii |
| Existing destination: skip and cancel | Destination unchanged, source retained | Dolphin plus real cross-device Wii move |
| Cross-device successful move | Matching destination bytes; source removed only on success | Wii SD to disposable USB |
| Unplug/replug or absent USB | UI handles missing device without crash or accidental operation | Wii |
| FAT/GPT partition discovery | Known fixture partitions and sizes listed correctly | Wii |
| Audio and media previews | Expected playback and responsive UI | Dolphin, Wii |
| SMB/NFS/FTP | Controlled LAN share lists/reads files; failures leave UI usable | Wii, optional Dolphin functional checks |

Use a dedicated `wiixplorer-test` directory with generated files. For transfer
tests include zero bytes, small text, a large deterministic binary, existing
destinations, nested directories, cancellation, and a destination-write failure.
Check hashes and existence explicitly. Dolphin folder sync supplies one SD card;
it does not establish real USB driver, hotplug, or cross-device behavior.
Keep archive traversal/security cases in host tests until extraction has been
hardened. Do not run deletion or move tests on existing saves or user files.

## Diagnose a guest fault

Record the displayed exception and Dolphin log's PC, LR, accessed address,
registers, and exact reproduction. Dolphin logs append; inspect only the boot
segment for this launch. A fresh profile avoids mixing runs. Map addresses using
the matching ELF:

```bash
/opt/devkitpro/devkitPPC/bin/powerpc-eabi-addr2line \
  -a -f -C -i -e boot.elf 0xFAULT_PC 0xFAULT_LR
/opt/devkitpro/devkitPPC/bin/powerpc-eabi-objdump -d -S boot.elf > /tmp/wiixplorer-disassembly.txt
```

Replace the placeholder addresses with the recorded hexadecimal values. Relaunch
with `-d` to use Dolphin's guest CPU debugger and break at the resolved function.
Single-core emulation makes stepping easier. Dolphin also implements a GDB
remote stub, including register/memory access and breakpoints; verify its enable
setting and port against the installed version before attaching
`powerpc-eabi-gdb boot.elf`. This document deliberately does not assume the
stub is enabled in the distributed Mac build.
[Dolphin GDB implementation](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/PowerPC/GDBStub.cpp).

## HBC-Reborn HOME overlay and remote tools

HOME now opens the pinned HBC-Reborn overlay in both builds. It replaces the
old WiiXplorer menu and supplies DEV, Exit and WiiMote tools. Its two app slots
are **Settings** (save settings) and **Diagnostics** (live MEM1/MEM2 heap space,
probe level, and a probe-flush button). DEV's Save uses the same settings action.
Restart app stays disabled until a reliable relaunch path exists. Exit choices
request the app's normal cleanup after the overlay/callback unwinds.

Debug builds start the low-priority remote agent and install its crash recorder;
release builds keep the overlay with its network listener and crash hook disabled.
The old app Wiiload receiver no longer competes for TCP 4299. The agent waits for
network startup to finish before the app calls `if_config()`. HBC's configured
netlog target is connected at debug startup, preserving existing stdout output.
The overlay's recent Log remains available without a PC receiver.

The SDK is downloaded by commit and SHA-256, compiled against the same official
libogc as the app, and never requires a sibling checkout. `scripts/hbc.py` runs
that SDK's official host client. For an isolated Dolphin run:

```bash
make debug PROBE_LEVEL=3
bash scripts/dolphin.sh --build debug --seconds 45
# In another terminal, use the profile printed by the launcher:
python3 scripts/hbc-smoke.py --profile /absolute/path/to/build/dolphin.XXXXXX
bash scripts/dolphin.sh --stop
python3 scripts/check-dolphin-smoke.py /absolute/path/to/build/dolphin.XXXXXX
```

Dolphin exposes guest sockets on the host's LAN address. The smoke script finds
that address without sending a probe packet, checks the app's identity, captures
browser/overlay/menu PNGs, exercises both app buttons, compares a disposable SD
file roundtrip byte for byte, checks probe integrity failures, and requests exit
while HOME is open. The launcher disables `XFBToTextureEnable`: the CPU-rendered
overlay and screenshot service must read real XFB bytes from guest RAM. With
texture-only copies, the original browser screenshot/frozen frame was purple.
The overlay borrows the completed off-screen XFB plus one temporary MEM1 buffer;
GX never writes those buffers while the overlay owns VI.

Manual client examples (Dolphin host address; real Wii only under a lease):

```bash
python3 scripts/hbc.py --wii ADDRESS status
python3 scripts/hbc.py --wii ADDRESS key h
python3 scripts/hbc.py --wii ADDRESS screen /path/to/home.png
python3 scripts/hbc.py --wii ADDRESS crash --elf /path/to/frozen/boot.elf
```

## Shared development Wii

Acquire the central queue lease before any contact with the bench Wii. Use the
workstation's configured wii-bench entry point; never fake its job variables or
bypass an unavailable lease server. The hardware runner rejects direct use.

```bash
job="$(python3 "$HOME/.wii-bench/wiibench.py" add \
  --name 'WiiXplorer NG HBC-Reborn smoke' --agent wiixplorer-ng \
  --timeout 300 --cwd "$PWD" -- python3 scripts/hbc-smoke.py --hardware)"
python3 "$HOME/.wii-bench/wiibench.py" wait "$job"
```

The runner freezes the debug DOL/ELF/map, build configuration and SHA-256 hashes
when the job starts, confirms HBC is ready, and sends the DOL with a finite
60-second fallback smoke limit. It backs up the SD settings, controls and probe
files locally, uses IOS58 with temp deletion disabled, performs the remote
checks, waits for HBC return, collects the final report, and restores those files.
Failure cleanup uses the official client's protection against exiting another
job's app. Artifacts remain in ignored `build/wii.*`; do not rebuild the input
while the job is starting. This tests a DOL launch, not a WAD install.

Two MEM2 allocator ranges preserve the HBC records at `0x91800000` through the
32-byte-aligned end of `hbc_crash_block` (`0x918000a0` for this SDK). Both ranges
participate in allocation, free, reallocation, free-space reporting and heavy
integrity checks. The tracked SDK patch adds listener shutdown/join and closes
the overlay on remote exit. It aborts active file requests and joins their owner
before app workers/devices are torn down. A host check covers the reservation,
free routing, joined teardown, and SD backup restoration on success/failure.

Dolphin results are functional evidence. Measure actual mount/transfer latency,
hotplug recovery, audio and sustained CPU/GPU behavior on the Wii. The remote
smoke covers HOME, settings, diagnostics, file serving and orderly exit; it does
not replace the full interactive file-operation matrix above.

## Observed validation

On 2026-10-02, a clean build produced the DOL/ELF/map using the installed
GCC 16.1.0 and official libogc 3.1.0. Host regressions passed. The helper's
prepare-only mode created an isolated SD/profile and matching artifact hashes.
Dolphin 2606a was launched through Launch Services with that configuration;
its log records the executable boot and Wii-memory setup. That initial observation established launch only; later frame, teardown and
HBC-Reborn checks are recorded below.



## Debug/release builds and grouped probes

`make release` builds `build/release/boot.{dol,elf,map}` with `-O2 -g`.
`make debug` builds `build/debug/boot.{dol,elf,map}` with `-Og -g3`.
They retain separate objects and generated resource headers. Select a
configuration explicitly when testing; each has its own matching DOL/ELF/map.
Release builds compile all probes out. Probe settings and compiler flags are
recorded in `build-info.json`; changing them invalidates the object files automatically.

```bash
make -j4 debug PROBE_GROUPS=cpu,gpu,threads,io,network PROBE_LEVEL=2
bash scripts/dolphin.sh --build debug --seconds 20
bash scripts/dolphin.sh --status
bash scripts/dolphin.sh --stop        # request close of the tracked instance
bash scripts/dolphin.sh --force-stop  # only the tracked instance, no SD-sync guarantee
bash scripts/dolphin.sh --stop-all    # this project's isolated profiles only
```

Like Wii64's `PERF_PROF` workflow, the app accumulates fixed-size counters and
writes a profiling file on the SD card, with frozen symbols retained alongside
the Dolphin profile. No logger allocations or file writes occur in interrupt
callbacks. The main thread flushes every 120 presented frames and before device
teardown; output is capped at 1 MiB per boot. A missing SD keeps the unflushed
`samples` array available to GDB. Levels are cumulative:

| Level | Cost | Probes |
| --- | --- | --- |
| 0 | Disabled | Same debug optimization/symbols, no instrumentation |
| 1 | Light | GUI updates, presentations, task enqueues, SD mounts/copies, network starts/requests |
| 2 | Timed operations | GUI work before presentation, GX copy/completion excluding VSync, tasks, mount/copy operations, network initialization; HTTP send-byte counters |
| 3 | Detailed/expensive | MEM2 linked-list integrity walk every 120 frames; texture alignment/FIFO-break checks; queue-depth/worker-render checks; per-chunk file and request-byte sampling |

Select fewer groups with `PROBE_GROUPS=cpu,gpu`. `PROBE_LEVEL=0` supplies a control
build for measuring probe overhead at the same optimization level. Retain
full/control/full runs with the same fixture and Dolphin settings. `count` is
sample count; `timed_count` is the denominator for mean timings. `value` is an
accumulated sample: level 1 counts operations; CPU/GPU level 3 counts failed
integrity/alignment/break checks; thread level 3 sums queue depth and attempted
worker renders; I/O and network detailed values count bytes. Idle runs do not
exercise every subsystem. Use file transfers and network requests to collect
those groups. Counters are diagnostic observations, not a complete race detector.

After a normal emulator stop, collect
`Load/WiiSDSync/apps/WiiXplorer/probes.csv` and run:

```bash
python3 scripts/probe-report.py /path/to/probes.csv
```

A timed host stop may need a forced close; the runner records `forced-stop.txt`
and does not leave that instance open. This is host-process cleanup, not proof
that the guest completed teardown. Dolphin folder sync holds guest writes in
memory, so force-closing it can lose the CSV. For durable profiling, use a copy
of a previously generated disposable `Load/WiiSD.raw`:

```bash
bash scripts/dolphin.sh --build debug --sd-image /path/to/disposable/WiiSD.raw
```

This disables folder sync for that run and writes into its **copied** raw image.
Let the application finish teardown so libfat flushes its cache, then extract
`apps/WiiXplorer/probes.csv` using a FAT image tool such as mtools `mcopy`.
The local verification also used Wii64's existing `scripts/sdimage_read.py`,
without adding a runtime dependency on the sibling checkout. Reject incomplete
CSV rows rather than comparing a partial log. These are guest elapsed times
under emulation, not physical Wii CPU/GPU performance measurements.

## Flashing and exit diagnosis

On this Intel Mac/Dolphin 2606a, PNG frame dumps reproduced intermittent loss of
textured sprites with the default Metal backend while text/background remained.
An unchanged application passed the same idle-frame comparison on OpenGL.
The macOS helper therefore selects `OGL`; override with `DOLPHIN_BACKEND=Metal`
to reproduce the comparison. This is a tested emulator workaround; physical Wii
rendering still needs its own verification. No speculative depth/VAT changes
from the investigation remain in the application.

```bash
bash scripts/dolphin.sh --build debug --capture --seconds 20
python3 scripts/check-dolphin-frames.py /path/to/profile/Dump/Frames
```

The frame checker needs Pillow installed in a Python virtual environment. It compares an **idle** browser region after startup and
excludes the shutdown tail. Keep controls neutral: navigation or window changes
are expected differences. Inspect capture duration and the last frame as well;
a short/truncated dump does not establish CPU progress. Frame dumping is opt-in
and can consume substantial disk space.

GDB reproduced an exit hang at `KMutexUnlock+32`: the old `CMutex` destructor
unlocked an unowned mutex, trapping forever with interrupts disabled in current
libogc. Its destructor now only destroys the unlocked mutex. Exit actions are
deferred until the GUI frame/callback unwinds. Producers join before dependent
objects are freed; GX completes before textures are released, and audio DMA
stops before GUI sounds/decoders are destroyed. Sound/task/network/FTP workers
retain wakeups rather than relying on racy suspend/resume handshakes.

For a guest teardown check independent of a fresh NAND lacking HBC/System Menu:

```bash
bash scripts/dolphin.sh --build debug --gdb-port 55020
powerpc-eabi-gdb /path/to/profile/artifacts/boot.elf
# (gdb) target remote 127.0.0.1:55020
# (gdb) continue
# Interrupt after startup, then request the same close flag used by the GUI:
# (gdb) set variable Application::exitApplication._M_base._M_i = 1
# (gdb) continue
# Interrupt and inspect cleanupComplete, singleton pointers, and the backtrace.
```

This installed GDB/Dolphin combination did not stop at the conditional software
breakpoint used during the investigation, so an explicit interrupt was used.
Dolphin's GDB stub accepts one session per boot and may not support detach.
The `_M_base._M_i` spelling is specific to this libstdc++ version. On real hardware,
return to HBC uses libogc's loader stub; a fresh Dolphin NAND has no HBC/System Menu
to launch, so a black return screen alone is not a cleanup failure.
References: [Dolphin GDB startup](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/Core.cpp),
[libogc loader return](https://github.com/devkitPro/libogc/blob/master/libogc/system.c),
[Wii64 profiling workflow](../Wii64/.dev/build_profiling.sh).

### Observed results (2026-10-02)

The old queue implementation failed a deterministic queued-before-worker-start
case. The corrected production queue/CMutex code passes 2,001 tasks from two
concurrent producers and idle shutdown under host ASan/UBSan. Production exit
request/dispatch, FAT-without-MBR, GPT, transfer, HTTP, devoptab, and heap-integrity
checks also pass. The original destructor failed the host mutex ownership assertion.

In Dolphin, the old destructor remained at `KMutexUnlock+32`; after the fix,
requesting the GUI close flag completed teardown, closed the guest GDB session,
and flushed a valid raw-SD report. The idle report contained 5,079 presentations,
42 heap walks, and 287,546 texture/FIFO samples with zero reported failures.
Guest GUI work averaged 210.2 microseconds and GX completion 1.0 microseconds;
these are not host GPU timings or hardware throughput measurements. File transfer,
FTP, sound playback, and physical Wii exit still require their scenario-specific
checks. The OpenGL frame comparisons passed; Metal comparisons failed.

The original failing DOL was retested unchanged on Metal: 846 captured frames
contained two sprite-drop intervals (frames 126–142 and 266–282), reproducing
the checker failure. The newer debug build passed a separate 492-frame Metal
capture. Preserve that distinction: backend sensitivity is confirmed for the
original build; this does not prove a standalone upstream Metal defect.

For finite debug smoke tests (including probe-disabled debug controls):

```bash
make -j4 debug PROBE_LEVEL=3
bash scripts/dolphin.sh --build debug --smoke-frames 600 --capture --seconds 20
```

The helper seeds `sd:/apps/WiiXplorer/smoke-frames.txt`. The debug build requests
normal exit after the specified number of frames **after** startup. A physical
loader can instead pass `--smoke-frames=600` as an application argument. Values
must be 1–36,000; no option is enabled by default, and release builds exclude
this path. The debug build reports `WiiXplorer: shutdown cleanup completed`
through libogc `SYS_Report` after cleanup. Check that message and the probe file,
then check for HBC return independently. A timed host kill is not a successful
smoke result. Fresh Dolphin NAND can stop on an absent return title; a configured
hardware test must use the proper loader stub.

The HBC-Reborn integration now reserves those MEM2 records; use the queued
hardware runner above for physical smoke tests.

Validate a finished smoke profile with:

```bash
python3 scripts/check-dolphin-smoke.py /path/to/profile
```

It checks artifact hashes, both teardown messages, complete CSV rows, expected
GUI update count when enabled, and zero CPU/GPU heavy-check failures. For raw-SD
runs, pass the extracted CSV with `--probes /path/to/probes.csv`.

The finite OpenGL smoke on 2026-10-02 passed: 600 GUI updates, 645 presentations
(including startup/fade), 641 PNG frames with zero browser-region flashes, five
heap checks and 34,808 GPU checks with zero failures, a complete synced CSV, and
both app/core teardown messages. Its tracked host process closed without forced
shutdown. Files/captures are intentionally under ignored `build/dolphin.*`.

### HBC-Reborn integration results (2026-10-02)

The debug build's official-client smoke passed in Dolphin: remote status/input,
HOME background capture, Settings save, Diagnostics/probe flush, a 3,200-byte
SD roundtrip, and exit while HOME was open. The final idle capture had 341 PNG
frames with no browser-region flashes and completed app/core teardown.

A leased physical Wii run passed the same agent/overlay/button/file checks and
returned to HBC 1.9.3 in 6.767 seconds (including channel reload/startup). The
final report contained 623 GUI updates, 667 presentations, five checks of both
MEM2 ranges and 44,369 GPU samples with zero reported failures. Idle GUI work
averaged 377 microseconds and GX copy/completion 1,305 microseconds on this Wii.
HBC reported no crash. The runner restored the original/absent settings, controls
and probe files and completed with exit code zero. Artifacts are in ignored
`build/wii.*`. An earlier run passed the app checks but found a runner directory
cleanup error; using trailing slashes for directory queries and preserving the
apps root corrected that error, which the repeat run verified.

Both debug/release builds and host checks pass. Release symbols contain no
probe/integrity/smoke helpers. Release HOME remains to be checked interactively;
these runtime results exercised the debug build. Audio, hotplug, large copies,
file-operation failures and sustained rendering still need separate scenarios.

## Transfer tests and interrupted hardware runs

See [TRANSFERS.md](TRANSFERS.md) for measured performance and bounded-transfer
contracts. `scripts/hbc-smoke.py` accepts `--copy-bench`, `--transfer-bench`,
`--ftp-smoke` and `--capture-log`. Hardware tests save the original SD settings,
controls and probes before installing private fixtures and restore them afterward.
If an unreachable app prevents cleanup, allow the debug smoke timer to return to
HBC, then queue `python3 scripts/hbc-restore.py build/wii.PROFILE` using that
failed test's exact artifact directory. Add `--wait 600` to wait for its safety
timer inside the lease. Never restore a different run's files.
The restoration command refuses to operate outside the hardware lease.

Dolphin FTP fixtures can be supplied with `scripts/dolphin.sh --build debug
--config-seed FILE --capture --seconds 180`; run `scripts/hbc-smoke.py --profile
build/dolphin.PROFILE --ftp-smoke` against that owned profile. The fixture must
set FTP autostart, port 2121 and a nonempty `FTPServer.CPassword`; the smoke
client decodes that private fixture rather than accepting an unauthenticated
server. Keep fixture settings out of
Git. Physical FTP tests use standard port 21. Omit `--capture` for timed network
tests: dumping every rendered frame can substantially slow emulated time. The
agent's screenshot command still checks individual frames.

The agent patch explicitly makes accepted sockets nonblocking before request
reads. A real POSIX accept test reproduced the old idle-header hang, and the
strict Dolphin test now requires an app rejection before the client timeout.
Hardware and Dolphin both passed idle rejection; Dolphin throughput remains
functional evidence, rather than a measure of native IOS speed. See
[HBC-NETWORKING.md](HBC-NETWORKING.md) for the upstream research.

Use GDB's `hbreak` with Dolphin's stub for teardown/exception breakpoints, for
example `hbreak ExitApp` and `hbreak agent_panic`. The hardware breakpoint run
caught a DSI while the old shutdown fade drew freed GUI children. Shutdown now
keeps the completed frame until GX is drained instead of drawing during owner
destruction. A frozen profile's DOL can be checked against its ELF with
`elf2dol boot.elf check.dol` and a byte comparison before trusting addresses.

## Dolphin-first validation (0.1.3, 2026-10-04)

Run the candidate in Dolphin before scheduling physical-Wii tests. The launcher
freezes its DOL/ELF/map and hashes under an ignored disposable profile. Normal
runs use batch mode so the owned window closes after core shutdown; `--debug`
keeps the interactive debugger. PowerPC/JIT and OSReport logs are retained.
Raw network payload logging stays disabled because it can expose PASS.

```sh
bash scripts/dolphin.sh --build debug --bench archive --smoke-frames 36000
python3 scripts/hbc-smoke.py --profile build/dolphin.PROFILE --archive-device sd
python3 scripts/check-dolphin-smoke.py build/dolphin.PROFILE
```

Replace `archive` with `memory`, `storage` or `copy`, and use `--memory-bench`,
`--storage-device sd` or `--copy-bench` on the controller. The launcher stages
a bounded debug-only `apps/WiiXplorer/bench.cfg`; release never reads it. Parsing
rejects unknown, duplicate, truncated, control-character and overlong arguments
atomically. No benchmark runs without explicit options. Emulator runs verify
operations, not physical bandwidth or USB hardware.

The checker rejects recorded guest exceptions/invalid accesses/panic/backtraces,
requires application and core teardown, verifies frozen hashes and CPU/GPU
integrity probes, and requires GUI activity. An intentional early remote exit
requires a passing controller report; a safety timer alone is not acceptance.
Use the matching frozen ELF to diagnose reported addresses before retrying.

The SDK opening animation discarded queued navigation before the following A
press, causing unintended Exit selection during the test. The local SDK patch
retains remote input until fully open and not closing. Host sanitizers exercise
the actual queue and portable UI, including varied frame delays. The controller
uses Back from Settings, then navigates to Diagnostics, and checks app identity
before subsequent operations. Temporary diagnostic probes were removed.

| Dolphin profile | Accepted checks |
| --- | --- |
| `build/dolphin.p9VRp8` | 30 production archive cases |
| `build/dolphin.UQ9HKS` | 48 verified MEM1/MEM2/LC operations |
| `build/dolphin.5lIV8d` | Authenticated FTP, empty/APPE/REST, idle/interrupted preservation, exit during upload |
| `build/dolphin.oTZC1d` | 12 verified SD read/write/copy rows |
| `build/dolphin.c3mW9l` | 15 verified staged-copy rows |

All five passed Settings/Diagnostics, file roundtrip, guest/core shutdown, frozen
hash/log/probe checks and zero CPU/GPU integrity failures. Plaintext credentials
were absent from both FTP logs. Batch windows closed. The shared level-3 DOL
SHA-256 is `1e7e7619791e581404c3f53f1cc0232fb8cfa82cd91907de959726178d55830c`.

The default level-1 debug run (`build/dolphin.7HCgns`) completed 600 GUI updates
and guest/core teardown. Its 625 captured frames had zero browser-region
flashes (maximum frame delta zero). This checks a static macOS/OpenGL browser;
other backends, transitions and sustained native rendering need their own tests.
Release boot (`build/dolphin.ShH4h5`) recorded no guest faults and completed
core shutdown after a bounded host stop; this is not interactive exit acceptance.
Release symbols exclude debug benchmark/configuration helpers.

`make check`, default debug and release builds passed. New host regressions
cover guest fault detection, bounded debug configuration, pinned HBC queue/UI
and FAT fixture cleanup. No archive library, compression default or production
transfer buffer was changed; idle release work is unchanged.

Native jobs `20261004-024106-510554`, `20261004-024108-6116ba` and
`20261004-024110-0e082d` were canceled to honor Dolphin-first testing. Recovery
`20261004-023553-772e84` completed at 08:22, restoring settings, controls and
probes after the earlier HBC USB hang.

Physical USB testing then exposed debug cleanup treating a nonempty-parent
EACCES as a packing failure. Host regressions and all 30 Dolphin cases passed
after the bounded occupancy fix (`build/dolphin.Pu4bol`). Job
`20261004-091300-812e6b` passed all 30 physical USB cases plus UI/file/exit,
returned to HBC and restored original settings/probes. See ARCHIVES.md for
retained earlier artifacts and limits. Physical memory speeds remain unresolved.
Authenticated FTP retry `20261004-091506-c92ea4` used the identical DOL already
accepted in Dolphin and passed SD/USB1 transfers, authentication, idle preservation,
UI/file checks and exit during upload, returning to HBC and restoring settings.
Artifacts are in `build/wii.wlxh9d9z`. Earlier connection failures did not
reproduce; their precise cause is not proven by this passing retry.

## Follow-up validation, 0.1.4

All hardware access, including recovery and diagnostic-file cleanup, uses the
shared Wii queue server. The local dispatcher is not a substitute for its lease.
Native memory job `20261004-105910-ed3057` passed 48 verified operations plus
UI/file/exit and settings restoration, after its identical DOL passed Dolphin
(`build/dolphin.8yAVUk`). Preserving the full DMAL cache tag address fixed the
first-DMA machine check. CSV rows are now synced outside timing, so failures
retain the last completed operation. See MEMORY.md for capacities and medians.

Fresh native SD and USB1 storage checks passed after Dolphin acceptance; both
are already aligned FAT32 with 32 KiB clusters. No repartitioning or production
buffer tuning was performed (STORAGE.md). FTP runtime tests now require a real
530 bad-password rejection and record passive endpoints without credentials.
Recent native control/data connection failures remain open (FTP.md).

Final clean v0.1.4 debug runs passed memory48 and FTP bad-password rejection,
full SD transfers, UI/file/exit, frozen hashes, probes and exception/teardown
checks (`build/dolphin.aCcoTN`, `build/dolphin.HeqKA7`). Default debug/release
builds and `make check` passed. Release ELF contains no memory benchmark or
temporary FTP trace symbols. The bounded release boot (`build/dolphin.Y54STO`)
recorded no guest fault markers and shut down the core after a host stop; this
is not interactive release exit acceptance. Temporary probes were removed;
production archive/backend/buffer defaults and idle release work are unchanged.
