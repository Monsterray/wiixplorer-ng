/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "TransferSocket.h"
#include "Diagnostics/Probes.h"
#include "Controls/Application.h"
#include <network.h>
#include <ogc/lwp_watchdog.h>
#include <ogc/ipc.h>
#include <fcntl.h>
#include <errno.h>
#include <unistd.h>

extern "C" u64 wx_transfer_deadline(u32 seconds) { return gettime()+secs_to_ticks(seconds); }
extern "C" int wx_transfer_expired(u64 deadline) { return gettime() >= deadline || wx_transfer_cancelled(); }

extern "C" int wx_transfer_cancelled() { return Application::isClosing(); }

extern "C" s32 wx_transfer_write(s32 socket, const void *data, u32 length)
{
    WX_SCOPE(NETWORK);
    if (!length) return 0;
    if (!data) return -EINVAL;
    if (wx_transfer_cancelled()) return -EINTR;
    if (length > 256*1024) length = 256*1024;
    u64 idleDeadline = gettime()+secs_to_ticks(10);
    const u64 totalDeadline = gettime()+secs_to_ticks(120);
    const u32 lowWater = 4096;
    // IOS can falsely report a nonblocking send as complete. Require enough
    // capacity for the entire blocking send instead, with a bounded poll.
    s32 result = net_setsockopt(socket, SOL_SOCKET, SO_SNDLOWAT, &lowWater, sizeof(lowWater));
    bool emulatedNonblocking = false;
    if (result < 0) {
        // Some Dolphin hosts (including Linux) cannot set SO_SNDLOWAT.
        // Host sockets report partial sends correctly; never use this fallback
        // on native IOS. /dev/dolphin is an emulator-only IOS device.
        s32 device = IOS_Open("/dev/dolphin", 0);
        if (device < 0) return result;
        IOS_Close(device);
        emulatedNonblocking = true;
    }
    s32 flags = net_fcntl(socket, F_GETFL, 0);
    s32 sendFlags = emulatedNonblocking ? flags | 4 : flags & ~4;
    if (flags < 0 || (sendFlags != flags && net_fcntl(socket, F_SETFL, sendFlags) < 0)) return -EIO;
    u32 done = 0;
    result = 0;
    while (done < length) {
        if (wx_transfer_cancelled()) { result = -EINTR; break; }
        if (gettime() >= idleDeadline || gettime() >= totalDeadline) { result = -ETIMEDOUT; break; }
        u32 chunk = length-done;
        if (chunk > lowWater) chunk = lowWater;
        if (!emulatedNonblocking) {
            struct pollsd ready = {socket, 0x0008, 0};
            result = net_poll(&ready, 1, 10);
            if (result < 0) break;
            if (ready.revents & 0x0060) { result = -ECONNRESET; break; }
            if (!(ready.revents & 0x0008)) continue;
        }
        result = net_write(socket, (const u8 *)data+done, chunk);
        if (result == -EAGAIN || result == -EINTR) {
            struct pollsd p = {socket, 0x0008, 0};
            if (net_poll(&p, 1, 10) < 0) usleep(1000);
            continue;
        }
        if (result <= 0 || result > (s32)chunk) { result = result < 0 ? result : -EIO; break; }
        done += result;
        idleDeadline = gettime()+secs_to_ticks(10);
    }
    if (done == length) result = done;
    if (sendFlags != flags) {
        s32 restored = net_fcntl(socket, F_SETFL, flags);
        if (restored < 0) { net_shutdown(socket, 2); result = restored; }
    }
    WX_PROBE(NETWORK, 1, result > 0 ? result : 0);
    WX_PROBE(NETWORK, 3, result < 0);
    return result;
}

extern "C" s32 wx_transfer_read(s32 socket, void *data, u32 length)
{
    WX_SCOPE(NETWORK);
    if (!length) return 0;
    if (!data) return -EINVAL;
    u64 deadline = gettime()+secs_to_ticks(10);
    if (length > 16384) length = 16384;
    s32 flags = net_fcntl(socket, F_GETFL, 0);
    if (flags < 0 || net_fcntl(socket, F_SETFL, flags | 4) < 0) return -EIO;
    for (;;) {
        if (wx_transfer_cancelled()) return -EINTR;
        if (gettime() >= deadline) return -ETIMEDOUT;
        s32 result = net_read(socket, data, length);
        if (result > (s32)length) return -EIO;
        if (result != -EAGAIN && result != -EINTR) {
            WX_PROBE(NETWORK, 1, result > 0 ? result : 0);
            WX_PROBE(NETWORK, 3, result < 0);
            return result;
        }
        struct pollsd p = {socket, 0x0003, 0};
        if (net_poll(&p, 1, 100) < 0) usleep(1000);
    }
}
