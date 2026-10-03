# FTP server

The default server uses the pinned ITotalJustice/ftpsrv core:

`FTPServer.cpp -> ftpsrv -> WiiXplorerFtpVfs -> DeviceHandler`

The existing FTP menu still starts/stops the server. Its settings retain the
existing port and password and add Username, Anonymous Access and Idle Timeout.
Default username: `wiixplorer`; anonymous access: OFF; idle timeout: 300 seconds;
maximum concurrent sessions: 4; shared transfer buffer: 32 KiB. Set a nonempty
username/password before starting, or explicitly enable read-only anonymous
access. Settings changes take effect on the next startup. No FTP callbacks are
registered and no PASS/password arguments are logged.

## Disabled lifecycle

With AutoStart OFF, normal startup never constructs or initializes the FTP
server. Opening its menu can create a small controller object, but it allocates
no mutex, buffers, session state or worker stack, opens no socket, enumerates no
devices and runs no background work. The uninitialized core retains only a null
state pointer (plus code/constants in the executable).

Enable initializes networking if necessary, allocates the core arena and a
32 KiB worker stack, binds the configured port, and starts one worker. Disable
sets the stop flag and joins that worker. The worker closes every session/data/
passive/listening socket, aborts incomplete staged uploads and calls
`ftpsrv_exit()` to clear/free its arena. Disable releases the stack; loop cycles
remain unchanged afterward. Re-enable creates fresh state. No device is mounted
or remounted by either transition. Application shutdown uses the same path.

The enabled loop polls at most 50 ms at a time. Native send blocks use the
hardware-tested capacity gate, with no loop waiting for write capacity inside
an individual send. Filesystem driver calls can still block internally; teardown
waits for an in-flight backend call to return. This is not a hard real-time
storage shutdown guarantee.

## Device paths and writes

`LIST /` reports currently mounted devices. `/sd/file` maps to `sd:/file`, and
`/usb1/file` maps to `usb1:/file`; the same adapter handles other mounted devices.
DeviceHandler is consulted at access time. Unmounted devices fail instead of
being mounted automatically. MountISFS OFF hides NAND; mounted NAND and DVD are
always read-only over FTP. Local ISFS write permission does not grant remote
NAND writes. Anonymous login, when explicitly enabled, is read-only everywhere.

STOR/APPE/resumed uploads write a private staging file. Failed/idle/interrupted
uploads retain the original. Successful EOF and close publish the file using
WiiXplorer's existing replacement helper; its two renames are not power-loss
atomic. Uploads are capped at 8 GiB, REST offsets at LONG_MAX (2 GiB on Wii),
paths below 992 bytes, and active transfers at four hours. FTP EOF cannot verify
how many bytes the sender intended. See [TRANSFERS.md](TRANSFERS.md).

## Comparison backend and validation

The existing ftpii code is retained, but is not linked into the default build.
For a comparison build:

```sh
make -j4 CONFIG=debug FTP_BACKEND=ftpii
```

Use `FTP_BACKEND=ftpsrv` (the default) to switch back. Build flags participate in
object rebuilds. The comparison wrapper also uses lazy startup/teardown, username
and password checks, anonymous read-only access, and argument-free command logs.
Its shared legacy scratch buffer also allocates only on Enable and is freed
on Disable. Its existing device/path implementation remains separate from the new adapter;
this first block does not claim modern VFS behavior for that legacy backend.

`make check` includes `tests/ftpsrv_integration.py`. It compiles the actual core,
adapter and server lifecycle with host thread/network shims under sanitizers,
uses temporary SD/USB device fixtures and deliberately fragments sends. It checks
no disabled arena/thread/polls/enumeration; LIST/RETR/STOR, empty/APPE/REST files;
NAND read-only/hidden behavior; authentication; timeout; four-client teardown;
staged abort; re-enable; and absence of passwords in logs. It opens only local
loopback sockets. These host fixtures supplement Dolphin/native-device testing.

[Imported version and local changes](source/FTPOperations/ftpsrv/UPSTREAM.md)
are tracked alongside the vendored source.

Validation on 2026-10-03 (official libogc 3.1.0 / devkitPPC r50-1):

| Check | Result |
| --- | --- |
| Default debug and release; retained ftpii debug build | Linked successfully |
| Host sanitizer regression suite and lazy lifecycle acceptance | Passed; bind-failure cleanup and all-client teardown/re-enable checked |
| Dolphin authenticated SD transfers, empty/APPE/REST, idle abort, active-upload exit | Passed; CPU/GPU integrity failures zero |
| Native Wii SD and USB1 LIST/RETR/STOR; empty/APPE/REST; idle preservation | Passed under shared lease job `20261003-134749-eec3f1` |
| Native active-upload app exit and return to HBC | Passed; original SD settings/controls/probes restored |

Native test artifacts are in ignored `build/wii.h_ijkl73`; Dolphin artifacts
are in ignored `build/dolphin.nacIBA`. Native CPU/GPU integrity probes reported
zero failures. The extra queued restoration job also completed successfully.
Repeated native UI enable/disable cycling and sustained multi-client load remain
follow-up tests; the lifecycle cycles were exercised with the real implementation
in the host harness.
