# Imported ftpsrv core

Source: [ITotalJustice/ftpsrv](https://github.com/ITotalJustice/ftpsrv/tree/99253bdd62fac99f251f1bf25043afdf3f4b38e7)

- Commit: `99253bdd62fac99f251f1bf25043afdf3f4b38e7`.
- Upstream version: **1.2.2**, from its CMakeLists.txt.
- Archive SHA-256: `b11427ade9d9a01acf401683f803a87188528d502763dd988e69b3186158b150`.
- Imported files: `src/ftpsrv.c`, `ftpsrv.h`, `ftpsrv_vfs.h`, `ftpsrv_socket.h`.
- License: MIT, Copyright 2024 TotalJustice. Notices remain in the source;
  [LICENSE](LICENSE) supplies the license text identified by the SPDX notices.
- No upstream application, UI, platform startup, configuration parser, logger,
  minIni dependency or device-mount code is imported.

`LOCAL.patch` records changes relative to these exact upstream files. The three
public headers are unchanged. To update, compare the new upstream revision,
reapply/review the patch, update this provenance and rerun the host/device tests.
Builds use committed source and need no network or sibling checkout.

Local core changes:

- Include the WiiXplorer build configuration (four sessions, a shared 32 KiB
  transfer buffer, 1024-byte protocol paths).
- Allocate the complete session/buffer arena only in init; clear credentials
  and free it in exit. Failed initialization also frees it. Poll arrays and
  directory entries use the worker stack rather than permanent mutable state.
- Limit download reads to the native 4 KiB send block to avoid repeatedly
  rereading 32 KiB after each short native send.
- Publish uploads through the VFS completion hook only after successful EOF
  and checked file/directory close; cleanup otherwise aborts staged uploads.
- Preserve fragmented control responses: use the remaining length correctly
  and finish sending the preliminary reply before data progression can queue
  its completion reply. Use memmove for overlapping command-buffer compaction
  and stop parsing if a session closes.
- Reset authentication on USER; permit configured-account and explicitly enabled
  anonymous login together; enforce read-only and anonymous write restrictions.
- Reject malformed/third-party/zero-port PORT targets and third-party passive
  peers. Separate the remote peer address from the local listener address.
- Update idle time only after actual command/response/data progress; retain a
  four-hour transfer cap. Reject invalid REST markers and propagate data/seek/
  listing/close failures.

The Wii socket implementation is **WiiXplorerFtpSocket.h**, not the upstream
platform header. It uses official libogc error/flag conventions, explicitly
configures accepted sockets, handles descriptor zero, and periodically tries
nonblocking accept because IOS can omit listener readiness. Native sends poll
for a configured 4 KiB low-water capacity before a blocking send; only verified
Dolphin host sockets may use nonblocking sends. It preserves HBC-Reborn's bounded
half-close/drain rule for normal replies, skipping the drain during Disable.

The VFS is **WiiXplorerFtpVfs.cpp**. It resolves `/sd`, `/usb1` etc. through
DeviceHandler's already-mounted devices, normalizes virtual paths, and never
mounts/remounts a device. NAND is hidden when MountISFS is off and is always
read-only over FTP, including when local NAND writes are enabled. DVD is also
read-only. Uploads retain the existing checked staging/recovery behavior.
