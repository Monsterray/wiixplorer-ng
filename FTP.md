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

On 2026-10-04, retries `20261004-014024-816734` (port 21) and
`20261004-023019-9b99a0` (port 2121) timed out establishing TCP connections.
The diagnostics overlay showed network ready and an initialized FTP worker
cycling, so this is an unresolved regression/environmental failure rather than
missing AutoStart. The earlier native acceptance above remains historical;
these retries do not pass. No server/socket behavior was changed on this evidence.
Job `20261004-024110-0e082d` repeats without optional network log forwarding
once HBC recovers. A timeout cannot distinguish IOS listener state from routing
or filtering; endpoint/packet evidence is still required if it repeats.

## Dolphin-first follow-up, 0.1.3

`build/dolphin.5lIV8d` passed authenticated SD roundtrip,
empty/APPE/REST, idle/interrupted upload preservation and exit during upload,
with completed guest/core teardown and valid integrity probes. No plaintext
password appeared in retained logs. Dolphin had no physical USB device. Native
retry `20261004-024110-0e082d` was canceled pending emulator validation; the
recent physical TCP connection failures remain unresolved. No FTP socket or
server behavior was changed by this validation block.

After Dolphin acceptance and confirmed settings recovery, native job
`20261004-091506-c92ea4` passed authenticated SD/USB1 LIST/RETR/STOR, empty
files, append/resume, idle preservation and exit during
upload. Normal UI/file checks and return to HBC 1.9.3 passed; original settings
and probes were restored. Artifacts are in `build/wii.wlxh9d9z`; its DOL matches
the accepted Dolphin FTP profile exactly. CPU/GPU integrity rows reported zero
failures. Earlier TCP failures did not reproduce, but this does not establish
whether their cause was input/accidental exit or another environmental condition.

## Authentication coverage and remaining native failures, 0.1.4

The controller now explicitly logs in with a wrong password and requires a 530
response before the authenticated transfer sequence. Earlier runtime passes
above tested successful authentication only; bad-password rejection was already
covered in the host integration harness. Passive endpoint metadata is retained
without command tracing or credentials, to distinguish control from data-port
failures. No server/socket behavior was changed in this block.

Dolphin profiles `build/dolphin.0A8pwF` and `build/dolphin.tvY98v` passed the new
bad-password check and full transfer/UI/exit sequence. Native job
`20261004-101524-dd56f8` rejected the bad password and accepted the valid login,
but timed out opening the first passive data connection. Job
`20261004-103056-697687` timed out connecting to the control port before login.
These are failures, despite the historical full native pass above. The latter
failure means rejected-login cleanup alone cannot explain all symptoms.

A bounded temporary socket trace build passed Dolphin first. Native job
`20261004-105547-f75ff7` started the app but lost agent responsiveness before FTP
checks, yielding no socket trace. Optional network logging was enabled; its
causal role is unproven. The safety timer subsequently returned to HBC; queued
recovery restored settings and a separate leased cleanup removed only the owned
trace file. Temporary source/launcher probes were removed. Further native
connection diagnosis is required; these failures do not establish a fix.

Final clean v0.1.4 Dolphin profile `build/dolphin.HeqKA7` passed the explicit
bad-password and full SD transfer/UI/exit sequence. Its identical DOL in native
job `20261004-110318-657c32`, without optional log forwarding, again rejected
bad credentials and accepted valid credentials, then timed out connecting to
passive port 49152 before NLST. `build/wii.56smlrj3/ftp-passive.json` confirms
the advertised host matches the control peer. The app remained responsive and
settings were restored. The native passive-connection failure remains open.

A command-first NLST experiment passed Dolphin (`build/dolphin.GxKltz`) but
native job `20261004-110757-ef0da4` still timed out connecting to port 49152 after
receiving the preliminary reply. Thus merely waiting for the transfer command
to arm accept does not explain the failure. The temporary client-order branch
was removed. Artifacts are `build/wii.j6f7iwy8`; settings were restored. Further
investigation needs native listener/error or packet evidence, rather than a
speculative change to the server's accept order.
