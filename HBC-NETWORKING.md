# Networking lessons from HBC-Reborn

Reviewed on 2026-10-03 against the local HBC-Reborn checkout at
`3b1e9a4e04fbb1afb98f516a2446ef9789877f8f`, the same revision pinned by
[our SDK builder](scripts/build-hbc-agent.py). That checkout has no tracked
working-tree changes; its only untracked item is a banner build tool. These
findings describe that source revision, not the independently installed HBC
version on the shared Wii. References below pin the inspected primary source.

## Native IOS behavior determines the safe socket path

HBC's hardware investigation found that a nonblocking `net_write` could
report 2048 bytes sent after queuing only 2040. Downloads lost eight bytes
around offset 4 KiB even though the send loop advanced by the reported count.
HBC therefore changes devnet reply sockets to blocking mode for sending and
restores their flags afterwards. Dolphin uses host sockets and did not expose
the defect. [Hardware findings](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/REVIEW.md),
[send implementation](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/channel/channelapp/source/devfile.c).

The HBC send loop checks elapsed time between `net_write` calls. A native
blocking call that never returns prevents that check from executing. HBC does
not configure `SO_SNDLOWAT` or poll sufficient capacity before each blocking
send. Its abort path requests shutdown from another thread and waits up to
three seconds; its review explicitly says this was not forced on hardware.
Consequently, HBC's timeout and abort code are useful reference code, but are
not evidence that stalled blocking sends have a hard time bound.
[TCP loop](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/channel/channelapp/source/tcp.c),
[abort implementation](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/channel/channelapp/source/devfile.c),
[validation limits](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/REVIEW.md).

WiiXplorer extends this approach in [TransferSocket.cpp](source/network/TransferSocket.cpp):
native sends require capacity polling and bounded chunks; only a verified
Dolphin device may use the host's correct nonblocking partial-send behavior.
The loop has separate idle and total batch deadlines. This is our additional
hardware-tested policy, not an upstream HBC technique. Retain the native
integrity and still-open stalled-peer tests when changing it.

Two other IOS quirks matter. HBC half-closes and drains for at most one second
before closing because an immediate native close reset the connection and
dropped queued replies. Its listener tries `accept` after every bounded poll,
since IOS may omit listener readability. These are directly implemented in
[tcp_close](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/channel/channelapp/source/tcp.c)
and the [agent listener](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/sdk/hbc_agent/agent.c).
Preserve the drain on replies and the periodic accept attempt. Explicitly set
accepted sockets nonblocking for reads: the upstream SDK assumes inherited
flags, while our [SDK patch](scripts/patches/hbc-agent.patch) handles host
accept semantics and closes a socket if setting the flags fails.

## What improved throughput in HBC

The following results are HBC's recorded measurements on IOS58 and 802.11g,
not fresh WiiXplorer measurements. [Source and measurements](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/REVIEW.md).

| Change | Recorded effect | Application here |
| --- | --- | --- |
| Replace fixed 20 ms receive waits with `net_poll`; raise IOS blocks to 16 KiB | Uploads rose from 0.62 to 0.90 MB/s | Already reflected in our bounded receive helper; native send safety needs separate chunk tuning |
| Raise standalone transfer priority above the drawing thread | Worst status round trip fell from 531 to 47 ms | Measure CPU scheduling before changing priorities |
| Overlap SD/zlib and network using a fixed queue of buffer pairs | A 5.3 MB ELF upload fell from 6.0 to 3.7 s | Already inherited through the SDK's smaller two-slot pipeline |
| Compress frames only when useful; checksum every raw frame | ELF rose to 1.45 MB/s up and 0.91 MB/s down; zeros to 4.2/4.9 MB/s | Use framed HBC transfers for verified developer transfers; do not silently change standard FTP/HTTP protocols |

The framed protocol caps raw frames at 64 KiB, validates raw/wire lengths,
checks CRC-32, and verifies total length. Download workers use zlib level 1
and skip compression for eight frames after one fails to shrink. The channel
uses four slots; the SDK Makefile uses two slots and a 16 KiB worker stack.
Each slot contains two aligned buffers with header headroom, so memory use
depends on slot count, not file size. This bounds memory while allowing disk,
CPU and network work to overlap.
[Protocol](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/docs/devnet.md),
[pipeline](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/channel/channelapp/source/devstream.c),
[SDK build configuration](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/sdk/hbc_agent/Makefile).

The channel's transfer priority is 80 above its UI's documented priority 64.
The SDK instead defaults to idle priority 40 and boosts transfers by eight;
its comment deliberately keeps transfers below the application's main
thread. Our [agent configuration](source/Diagnostics/HbcAgent.cpp) leaves
that default in place, while [FTPServer.cpp](source/FTPOperations/FTPServer.cpp)
currently uses priority 30. Raising either blindly would not reproduce the
channel's scheduling arrangement. Measure frame time and transfer latency
together under a busy UI, then adjust only if starvation is demonstrated.
[Channel priority](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/channel/channelapp/source/devnet.h),
[SDK priorities](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/sdk/hbc_agent/agent.c).

HBC rejected larger socket buffers, blocking receives and zlib level 6 after
measurement. Its documentation attributes the 16 KiB IPC block choice to
libogc's 64 KiB network heap. These are findings for its tested stack, not
guarantees for every future libogc/IOS combination. HBC reserves a 320 KiB
MEM1 arena for hot zlib state; its channel calls `zmem_init`, but this SDK's
agent does not, so the reserved-arena benefit does not automatically apply
to the embedded agent. Keep it as a profiling candidate instead of adding
an unmeasured permanent reservation.
[Performance discussion](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/docs/devnet.md),
[arena](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/channel/channelapp/source/zmem.c),
[channel initialization](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/channel/channelapp/source/main.c),
[SDK initialization](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/sdk/hbc_agent/agent.c).

## Measurement and remaining work

HBC's benchmark measures status latency and verified upload/downloads of
random data, zeros and an ELF; status reports network, disk, CPU and wire-byte
costs separately. Its documented A/B method interleaves three rounds because
single Wi-Fi runs vary by 30% or more. The script reports decimal MB/s;
WiiXplorer's transfer notes report binary MiB/s, so convert units before
comparing results. Dolphin validates functionality; native IOS hardware is
required for throughput and send-integrity conclusions.
[Benchmark source](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/tests/wii_netbench.py),
[A/B findings](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/docs/devnet.md),
[hardware validation guidance](https://github.com/Monsterray/hbc-reborn/blob/3b1e9a4e04fbb1afb98f516a2446ef9789877f8f/.agents/skills/hbc-build-and-review/SKILL.md).

The next useful experiments are interleaved native comparisons of send
capacity/chunk policies, then scheduling under CPU/GPU load. Record time
spent polling separately from successful write time, retain exact byte
comparisons, and keep the stalled receiver connected until another request
answers. A good throughput number without those checks is insufficient.
Current results and unresolved physical FTP/SMB/NFS coverage belong in
[TRANSFERS.md](TRANSFERS.md), rather than being inferred from HBC's older
channel measurements. Any additional pipelining for standard transfers
should be justified by measured disk/network idle time and retain fixed
buffer counts, cancellation and staged publication.
