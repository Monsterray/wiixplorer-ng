# WiiXplorer NG 0.1.16 testing build

Not a validated release candidate. FTP and intermittent Dolphin exit failures
remain release blockers. The build is provided for controlled local testing.
Copy the contents of `release/wiixplorer/` into `sd:/apps/wiixplorer/`.
Keep existing settings; do not delete `sd:/apps/WiiXplorer/`. The package includes
languages, icon, version metadata and available dependency notices. Debug is
separate at `release/wiixplorer-debug/`; set Language Path to the installed
Languages folder when using a different app folder. Never install update.xml;
the obsolete network updater remains disabled.

Use disposable files and retain originals during testing. Record the version,
IOS, device/filesystem, trigger, expected/actual behavior and video/crash details.
Complete inherited asset/binary provenance remains open before public
redistribution; see LICENSE.md.

## Confirmed coverage

* `make check`: host ASan/UBSan and real pinned codec regressions passed.
* Debug level-3 and release level-0 builds passed. Both automatically stage a
  ready-to-copy app; release contains no diagnostic probes or remote SDK listener.
* Eleven production feature groups passed first in Dolphin, then shared-Wii
  queue job `20261007-183859-708a2b`: PNG/JPEG/GIF/TIFF/BMP/GD/GD2 roundtrips,
  height-only resize and flips, screenshot encoding, exact UTF-8 text saves,
  empty/standard MD5 and copy/rename/delete. App controls, settings/probe buttons,
  file roundtrip and return to HBC 1.10.0 passed; original SD settings restored.
* Authenticated FTP SD protocol checks passed in Dolphin, including bad-password
  rejection, LIST/RETR/STOR, append/resume, timeout and preservation on aborted
  upload/exit in individual runs. Other runs failed during exit; a clean run
  does not establish reliable shutdown.
  These emulator results do not prove real USB/network behavior.
* Seven production media groups passed first in Dolphin, then queue job
  `20261007-200831-a4e0ab`: GIF reload, TPL bounds, streaming JPEG, audio ring,
  RGB stride, PDF raster and movie workers. Return to HBC and restoration passed.
  These checks do not establish audible playback or every player control.
* Final level-0 release passed a bounded 20-second Dolphin boot smoke in
  `build/dolphin.b1FdUe`; no guest faults were recorded and host stop completed.
  This checks startup, not the unresolved application exit path.

## Release blockers

Native FTP remains unreliable. Queue jobs with bounded startup waits rejected a
bad password and authenticated correctly, then timed out connecting the passive
data socket before NLST. The last diagnostic job `20261007-210754-d34839`
timed out connecting the control socket despite a successful listener bind.
All failed jobs restored original SD settings. Native SD/USB transfers and
Disable/re-enable remain unconfirmed. FTP AutoStart remains OFF by default.

Dolphin intermittently reports ISI/unknown-instruction exceptions after app
cleanup. Successful boot/exit runs do not establish stable shutdown. The test
harness fails on these exceptions and prevents the physical-Wii test from
running. Experimental FTP binding/pre-accept and direct Dolphin loader-hook
changes did not resolve these failures and have been reverted. No root cause
or fix is claimed for either blocker.

## Fixes and resource effects

Image and text writes now publish through the existing transfer staging policy,
retaining an original on write/close/encoder failure. TIFF requires a read/write
stream. Height-only image resize, screenshot result/error propagation and GD2
extension, language filenames/paths, and empty/truncated/error MD5 handling are
corrected. MD5 keeps its existing 1 MiB streaming buffer; the legacy context has
only a 32-bit byte counter, so files above 4 GiB minus one byte are rejected
instead of producing a wrong checksum. Other formats/buffers/defaults were not
retuned from guesses.

HBC-Reborn SDK, host client and project queue client pin 1.10.0 at
`a797ba98539e863a47409bfd8d62e4cf43f84d9d`. Packages include the commit/checksum
manifest. The final pin changes queue tooling only; the SDK used for the recorded
hardware tests is byte-identical. Its retained MEM2 records reserve 4,416 bytes (4,256 more than before);
allocator routing remains owned by WiiXplorer. New feature probes exist only
in debug and run only when explicitly requested. Idle release overhead from
these probes is zero. See DEBUGGING.md for the strict emulator gate and queued
hardware workflow.

## Manual test checklist

* SD/USB browsing, copy/move/rename/delete, empty folders, overwrite and cancel.
* Image formats, resize/rotate/flip/convert, zoom/slideshow, screenshots.
* Text editing (UTF-8 and multiline), PDF pages, font/language selection.
* MP3/OGG/WAV/BNS/AIFF music and movie playback, seek/loop/volume and close.
* ZIP/7z/RAR/U8/RARC browsing/extraction and ZIP creation.
* FTP server enable/auth/LIST/RETR/STOR/disable/re-enable; FTP client.
* SMB/NFS with a configured test server, DVD/Wii disc and physical USB keyboard.
* DOL/ELF launching and return; BootMii only on a suitable configured console.
* Format only explicitly disposable media. NAND access stays hidden/read-only
  according to settings. These destructive/platform-specific paths are not
  exercised on the shared development Wii merely to check a box.

Diagnostic automation in 0.1.15 adds bounded first-fault evidence, exact-DOL
repeat checks and a minimal HOME/exit scenario. Earlier successful jobs above
remain historical; automation improvements do not fix the open runtime blockers.

Diagnostics in 0.1.16 isolate the zero-address shutdown exception with a tiny
libogc-only video/exit fixture: two normal-JIT failures and two interpreter
passes on Dolphin 2606a. A report before exit changes reproduction, so the saved
fixture omits it. GDB launch now enables debugger mode; CPU selection is explicit
and recorded. No application exit workaround or native FTP fix is claimed.
See DEBUGGING.md for reproduction and the unverified Dolphin next-PC hypothesis.
Normal-JIT exceptions still fail acceptance; no physical test was submitted
through an interpreter-only gate.

The latest 0.1.16 interpreter FTP diagnostic reached the SD protocol assertions
but failed the unfinished-upload timeout response watchdog. The SDK remained
responsive during that wait. It is a failed test, not FTP acceptance; USB and
native FTP remain unconfirmed. All owned Dolphin processes were closed.
