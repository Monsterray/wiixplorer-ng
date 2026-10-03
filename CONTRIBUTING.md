# Contributing

Start with the toolchain and ordinary `make deps`, `make -j4`, `make check`
commands in [README.md](README.md). Use the same commands on macOS, Linux, or
in Windows's devkitPro MSYS2 shell. Use official libogc, not a mixed installation
of libogc and libogc2. Dependencies build privately under `.deps/`.

Keep changes focused and preserve source notices. For dependency compatibility
fixes, edit the versioned patch and rebuild with `make deps`; edits inside
`.deps/work/` are disposable. Record dependency upgrades and checksums in
`scripts/build-deps.py` and update [DEPENDENCIES.md](DEPENDENCIES.md).

Before submitting a pull request:

```sh
make check
make -j4 release
make -j4 debug
git diff --check
git status --short
```

Use a host compiler for `make check`; override `HOST_CC`/`HOST_CXX` when
needed (for example `make check HOST_CC=clang HOST_CXX=clang++`). Explain the problem, resulting behavior, and checks
performed in the pull request. Report runtime checks separately from compilation.
For filesystem changes, include error, cancellation, and existing-destination
cases, using disposable fixtures. Follow [DEBUGGING.md](DEBUGGING.md) for Dolphin
and hardware checks. Do not contact the shared development Wii outside its lease.

Do not commit compiled outputs, downloaded SDK/dependencies, test SD images,
logs, credentials, editor state, or AI instruction/tool files. Human-facing
project documentation belongs in Git. `.gitignore` handles local files and
`.gitattributes` keeps scripts and patches usable across platforms.

Current CI builds against the official devkitPro container and runs host
regressions. Native macOS and Windows changes should include local build results
when available. Legacy warnings are still being triaged; do not globally relax
compiler diagnostics to hide callback type or ownership errors.

Select `--build debug` or `--build release` when using the Dolphin helper. Probe
levels/groups, finite captures, process cleanup, and guest exit verification are
described in [DEBUGGING.md](DEBUGGING.md#debugrelease-builds-and-grouped-probes).
Do not compare emulator timings with physical Wii performance numbers.

Asset filenames under `data/images`, `data/fonts`, and `data/sounds` must create
unique C identifiers when dots become underscores. Avoid spaces, punctuation,
and names differing only in case. Resource declarations are generated under
`build/<configuration>/Memory/filelist.h` and are not committed.
