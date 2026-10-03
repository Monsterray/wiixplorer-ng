# License and provenance status

Retain each source file's original copyright and license notice. Many application
files specify GNU GPL version 3 or later; device/network files also include
permissive notices. These existing notices govern their respective files.

This document is an inventory note, not a replacement license or a claim that
every file has the same license. A complete release inventory remains necessary:

- Include the full applicable license texts alongside redistributed source/binaries.
- Record origin, version, license, and modifications for bundled third-party code.
- Confirm redistribution terms for fonts, images, sounds, and bundled executables.
- Record exact external library versions and notices used for each release.

Original application authors include Dimok, r-win, and dude. Upstream credits
identify NeoRame for graphics and Tantric for libwiigui; the Homebrew metadata and
source headers contain additional contributors. NG changes are maintenance
modifications to that imported project and do not replace upstream attribution.

`data/binary/magic_patcher.o` and embedded application-booter binaries are
inherited upstream artifacts. The magic-patcher source was not found in the
original archive. Retain these notices and resolve binary provenance before
release. External source origins and rebuild details are in
[DEPENDENCIES.md](DEPENDENCIES.md).

The pinned HBC-Reborn agent dependency is GPL version 2 or later upstream; its
netlog header is public domain. The rebuild retains the full agent license in
`.deps/prefix/licenses/hbc-agent/COPYING`. Its revision, archive hash and local
lifecycle patch are documented in [DEPENDENCIES.md](DEPENDENCIES.md).

The vendored ftpsrv core is MIT, Copyright 2024 TotalJustice. Its original
notices remain in each core file, with [license text](source/FTPOperations/ftpsrv/LICENSE)
and [pinned provenance/local modifications](source/FTPOperations/ftpsrv/UPSTREAM.md).
The WiiXplorer VFS, socket and lifecycle integration files retain their own notices.
