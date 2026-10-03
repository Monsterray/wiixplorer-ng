 /****************************************************************************
 * Copyright (C) 2010
 * by Dimok
 *
 * This software is provided 'as-is', without any express or implied
 * warranty. In no event will the authors be held liable for any
 * damages arising from the use of this software.
 *
 * Permission is granted to anyone to use this software for any
 * purpose, including commercial applications, and to alter it and
 * redistribute it freely, subject to the following restrictions:
 *
 * 1. The origin of this software must not be misrepresented; you
 * must not claim that you wrote the original software. If you use
 * this software in a product, an acknowledgment in the product
 * documentation would be appreciated but is not required.
 *
 * 2. Altered source versions must be plainly marked as such, and
 * must not be misrepresented as being the original software.
 *
 * 3. This notice may not be removed or altered from any source
 * distribution.
 *
 * for WiiXplorer 2010
 ***************************************************************************/
#include <unistd.h>
#include <malloc.h>
#include <errno.h>
#include <string.h>
#include "FTPServer.h"
#include "Settings.h"
#include "Language/gettext.h"
#include "Tools/gxprintf.h"
#include "network/networkops.h"
#ifndef WX_FTP_LEGACY
#define WX_FTP_LEGACY 0
#endif
#if WX_FTP_LEGACY
#include <network.h>
#include "MountVirtualDevices.h"
#include "ftpii/ftp.h"
#include "ftpii/net.h"
#include "ftpii/virtualpath.h"
#else
#include "ftpsrv/ftpsrv.h"
#endif

FTPServer *FTPServer::instance = NULL;
std::atomic<s32> FTPServer::listenerStatus(0);
std::atomic<u32> FTPServer::eventCycles(0), FTPServer::listenerPort(0);
std::atomic_bool FTPServer::stopRequested(true);
extern "C" int wx_ftp_stopping(void) { return FTPServer::stopping(); }

FTPServer::FTPServer() : ftp_running(false), worker(LWP_THREAD_NULL), stack(NULL), server(-1) {}
FTPServer::~FTPServer() { ShutdownFTP(); }
void FTPServer::lockLifecycle() { while (lifecycleBusy.test_and_set(std::memory_order_acquire)) usleep(1000); }
void FTPServer::unlockLifecycle() { lifecycleBusy.clear(std::memory_order_release); }

void FTPServer::stopLocked()
{
    stopRequested = true;
    if (worker != LWP_THREAD_NULL) {
        LWP_JoinThread(worker, NULL);
        worker = LWP_THREAD_NULL;
    }
    free(stack); stack = NULL;
    // The worker owns core cleanup. Startup failures clean up synchronously.
    ftp_running = false;
    listenerStatus = 0; listenerPort = 0;
}

void FTPServer::StartupFTP()
{
    lockLifecycle();
    if (ftp_running) { unlockLifecycle(); return; }
    stopLocked();
    if (!Settings.FTPServer.Port || !Settings.FTPServer.IdleTimeout ||
        (!Settings.FTPServer.Anonymous && (!Settings.FTPServer.User[0] || !Settings.FTPServer.Password[0])) ||
        strpbrk(Settings.FTPServer.User,"\r\n") || strpbrk(Settings.FTPServer.Password,"\r\n")) {
        listenerStatus = -EINVAL;
        gxprintf("%s",tr("Set an FTP username and password before starting.\n"));
        unlockLifecycle(); return;
    }
    if (!IsNetworkInit()) Initialize_Network();
    if (!IsNetworkInit()) { listenerStatus = -ENETDOWN; unlockLifecycle(); return; }
    stopRequested = false;
    stack = memalign(32, 32768);
    if (!stack) { stopRequested = true; listenerStatus = -ENOMEM; unlockLifecycle(); return; }
    int rc;
#if WX_FTP_LEGACY
    MountVirtualDevices();
    set_ftp_username(Settings.FTPServer.User, Settings.FTPServer.Anonymous);
    set_ftp_idle_timeout(Settings.FTPServer.IdleTimeout);
    set_ftp_password(Settings.FTPServer.Password[0] ? Settings.FTPServer.Password : NULL);
    rc = init_ftp_buffers();
    server = rc < 0 ? rc : create_server(Settings.FTPServer.Port);
    rc = server < 0 ? server : 0;
#else
    FtpSrvConfig cfg = {};
    snprintf(cfg.user,sizeof(cfg.user),"%s",Settings.FTPServer.User);
    snprintf(cfg.pass,sizeof(cfg.pass),"%s",Settings.FTPServer.Password);
    cfg.port = Settings.FTPServer.Port;
    cfg.anon = Settings.FTPServer.Anonymous;
    cfg.write_account_required = true; // explicitly enabled anonymous access is read-only
    cfg.timeout = Settings.FTPServer.IdleTimeout;
    // No logging/progress/device callbacks are registered, even while enabled.
    rc = ftpsrv_init(&cfg);
    volatile char *secret = cfg.pass;
    for (unsigned i=0;i<sizeof(cfg.pass);++i) secret[i] = 0;
#endif
    if (rc >= 0) {
        ftp_running = true;
        rc = LWP_CreateThread(&worker, threadEntry, this, stack, 32768, 30);
    }
    if (rc < 0) {
        stopRequested = true; ftp_running = false;
#if WX_FTP_LEGACY
        cleanup_ftp(); cleanup_ftp_buffers(); set_ftp_password(NULL); set_ftp_username(NULL, false);
        if (server >= 0) net_close(server);
        server = -1; UnmountVirtualPaths();
#else
        ftpsrv_exit();
#endif
        free(stack); stack = NULL; worker = LWP_THREAD_NULL;
        listenerStatus = rc == -1 ? -EIO : rc;
    } else {
        eventCycles = 0; listenerStatus = 1; listenerPort = Settings.FTPServer.Port;
        gxprintf("%s %u...\n", tr("Listening on TCP port"), Settings.FTPServer.Port);
    }
    unlockLifecycle();
}

void FTPServer::ShutdownFTP()
{
    lockLifecycle();
    const bool active = worker != LWP_THREAD_NULL;
    stopLocked();
    unlockLifecycle();
    if (active) gxprintf("%s",tr("Server was shutdown...\n"));
}
void *FTPServer::threadEntry(void *arg) { static_cast<FTPServer *>(arg)->executeThread(); return NULL; }
void FTPServer::executeThread()
{
    while (!stopRequested) {
        ++eventCycles;
#if WX_FTP_LEGACY
        const int failed = process_ftp_events(server);
#else
        const int failed = ftpsrv_loop(50) != FTP_API_LOOP_ERROR_OK;
#endif
        if (failed) { listenerStatus = -EIO; break; }
        usleep(1000);
    }
#if WX_FTP_LEGACY
    cleanup_ftp(); cleanup_ftp_buffers(); set_ftp_password(NULL); set_ftp_username(NULL, false);
    if (server >= 0) net_close(server);
    server = -1; UnmountVirtualPaths();
#else
    ftpsrv_exit();
#endif
    ftp_running = false;
    listenerPort = 0;
}
