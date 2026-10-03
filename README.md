# WiiXplorer NG

WiiXplorer NG is a maintenance fork of the Wii file browser developed by Dimok,
r-win, and dude, with graphics by NeoRame and a GUI based on Tantric's libwiigui.
Original notices and assets are retained. The obsolete Google Code application
and language updater is disabled; install updates manually.

## Build

Install [devkitPro's Wii toolchain](https://devkitpro.org/wiki/Getting_Started/devkitPPC)
(`wii-dev`) and these package-managed PowerPC libraries:

```sh
# Use dkp-pacman on installations which provide that command instead of pacman.
pacman -S ppc-libpng ppc-freetype ppc-mxml ppc-libmad ppc-zlib ppc-bzip2 ppc-brotli
```

Use GNU Make, Bash, Python 3.10+, curl, and patch. On Windows, run commands in the
devkitPro MSYS2 shell with its POSIX Python; PowerShell alone is insufficient.
macOS and Linux use a normal shell. Keep devkitPro's configured `DEVKITPRO` and
`DEVKITPPC` environment variables; on a default Unix installation:

```sh
export DEVKITPRO=/opt/devkitpro
export DEVKITPPC="$DEVKITPRO/devkitPPC"
export PATH="$DEVKITPPC/bin:$DEVKITPRO/tools/bin:$PATH"
make deps
make -j4
make check
```

`make deps` downloads checksum-pinned source archives and rebuilds missing
historical Wii ports with the installed compiler. It writes only to `.deps/`;
it does not change the shared SDK or require administrator access. Compatibility
patches live in `scripts/patches/`. See [DEPENDENCIES.md](DEPENDENCIES.md) for
origins, versions, and limitations. Bootstrap needs internet access on its first
run; subsequent builds reuse the verified downloads and compiled objects.
`JOBS=4 make deps` controls dependency compilation parallelism.

The Makefile uses devkitPro's standard `wii_rules` and official libogc. It
supports checkout paths containing spaces. `make release` produces
`build/release/boot.{dol,elf,map}` with `-O2 -g`; `make debug` produces
`build/debug/boot.{dol,elf,map}` with `-Og -g3`. Keep the matching ELF/map for
debugging. Generated headers also stay under their build directory. `make clean` removes
application outputs; deleting `.deps/work` and `.deps/prefix` forces dependency
recompilation. The configurations keep separate objects; changing flags rebuilds affected objects.
Debug probes use `PROBE_GROUPS=cpu,gpu,threads,io,network` and `PROBE_LEVEL=0..3`
(default 1). Release compiles them out. See [profiling and shutdown checks](DEBUGGING.md#debugrelease-builds-and-grouped-probes).

Validated locally with devkitPPC r50-1 / GCC 16.1.0, libogc 3.1.0-1, and current
PowerPC portlibs on Intel macOS. Linux CI uses the official devkitPro container;
its first successful run and a native Windows build remain to be verified.

## Run and contribute

Copy `build/release/boot.dol`, `HBC/meta.xml`, and `HBC/icon.png` to
`sd:/apps/wiixplorer-ng/` for Homebrew Channel. Settings still use the upstream
`sd:/apps/WiiXplorer/WiiXplorer.cfg` location.

`make run` opens an isolated Dolphin profile. Set `DOLPHIN_EXE` or
`DOLPHIN_APP` if Dolphin is installed elsewhere.

[STORAGE.md](STORAGE.md) records native SD/USB speeds and partition recommendations.
[MEMORY.md](MEMORY.md) describes memory capacities and the pending native MEM1/MEM2/LC benchmark.
[DEBUGGING.md](DEBUGGING.md) describes isolated Dolphin tests, crash
symbolization, and the shared development Wii queue. [CONTRIBUTING.md](CONTRIBUTING.md)
contains the contributor workflow. [TRANSFERS.md](TRANSFERS.md) documents transfer
limits, replacement recovery and measured SD copy performance. [REVIEW.md](REVIEW.md) records completed
safety fixes, optimization candidates, and ranked future work.

Host regression checks compile production transfer, GPT, file-callback, and
HTTP functions with platform stubs and address/undefined-behavior sanitizers.
They require a host C/C++ compiler and do not replace runtime tests on Wii.

`VERSION` holds the Major.Minor.patch application version; keep `HBC/meta.xml`
in sync when bumping it. `gitrev.sh` includes that version and `git describe`
in credits; source archives without Git retain the version with an `unknown`
revision. Generated versions, dependency caches, test
profiles, editor state, and AI instructions are ignored by Git.

## Provenance and licenses

[LICENSE.md](LICENSE.md) records the imported tree's license/provenance status.
Retain the original file notices. A complete asset and bundled-binary license
inventory remains necessary before publishing a release.

## HOME menu

HOME opens HBC-Reborn's overlay, with DEV, Exit and WiiMote tools. The two app
buttons are **Settings** (save) and **Diagnostics** (heap space and probe export).
Debug builds also expose HBC-Reborn's remote input, screenshots, file access and
crash reports. Use `python3 scripts/hbc.py --wii ADDRESS status`; physical bench
Wii commands must run under the shared queue lease. The pinned SDK/client build
locally with `make deps`. See [DEBUGGING.md](DEBUGGING.md) for repeatable tests.

## FTP server

The default server uses pinned ftpsrv with the existing FTP menu. AutoStart is
OFF by default; disabled FTP has no worker, sockets, session arena or polling.
Set a username/password before enabling it. Anonymous access defaults OFF.
See [FTP.md](FTP.md) for lifecycle, mounted-device paths, limits and the retained
ftpii comparison build.
