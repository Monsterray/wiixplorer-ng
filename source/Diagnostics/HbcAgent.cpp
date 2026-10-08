/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "HbcAgent.h"
#include "Probes.h"
#include "Memory/mem2.h"
#include "Settings.h"
#include "VideoOperations/video.h"
#include "gitrev.h"
#include "sys.h"
#include "network/networkops.h"
#include "FTPOperations/FTPServer.h"
#include <malloc.h>
#include <stdio.h>
#include <hbc_agent.h>
#if WX_DEBUG_BUILD
#include <hbc_netlog.h>
#endif

#if WX_DEBUG_BUILD
static hbc_netlog_block savedLog;
#endif
void HbcAgentPrepare()
{
#if WX_DEBUG_BUILD
    // IOS reload clears low memory. Preserve only the validated HBC log target.
    memcpy(&savedLog, (const void *)HBC_NETLOG_ADDR, sizeof(savedLog));
    if (savedLog.magic != HBC_NETLOG_MAGIC || savedLog.version != HBC_NETLOG_VERSION ||
        savedLog.check != hbc_netlog_check(&savedLog)) {
        memcpy(&savedLog, (const void *)HBC_NETLOG_KEEP_ADDR, sizeof(savedLog));
        if (savedLog.magic != HBC_NETLOG_MAGIC || savedLog.version != HBC_NETLOG_VERSION ||
            savedLog.check != hbc_netlog_check(&savedLog)) memset(&savedLog, 0, sizeof(savedLog));
    }
#endif
}
static bool ready;
static char mem1[40], mem2[40], probes[32], network[40];
static bool SaveSettings(void *)
{
    bool saved = Settings.Save();
    hbc_agent_toast(saved ? "Settings saved" : "Couldn't save settings");
    return saved;
}
static void SaveSettingsButton(void *user) { SaveSettings(user); }
static void FlushProbes(void *)
{
    wx_probe_flush();
    hbc_agent_toast("Probe flush requested; see probes.csv");
}
static bool ExitChoice(int choice, void *)
{
    // Request shutdown after the overlay/callback has unwound.
    switch (choice) {
        case HBC_AGENT_EXIT_HBC: Sys_LoadHBC(); break;
        case HBC_AGENT_EXIT_SYSTEM_MENU: Sys_LoadMenu(); break;
        case HBC_AGENT_EXIT_RESTART: Sys_Reboot(); break;
        case HBC_AGENT_EXIT_POWER_OFF: Sys_Shutdown(); break;
        default: return false;
    }
    return true;
}
static void UpdateInfo(void *)
{
    snprintf(network, sizeof(network), "%s; FTP %d :%u (%u)", IsNetworkInit() ? "Ready" : "Pending", FTPServer::status(), (unsigned)FTPServer::port(), (unsigned)FTPServer::cycles());
    snprintf(mem1, sizeof(mem1), "%u KiB free", (unsigned)mallinfo().fordblks / 1024);
    snprintf(mem2, sizeof(mem2), "%u KiB free", MEM2_freesize() / 1024);
}
void HbcAgentInit()
{
#if WX_DEBUG_BUILD
    if (savedLog.magic == HBC_NETLOG_MAGIC) {
        memcpy((void *)HBC_NETLOG_ADDR, &savedLog, sizeof(savedLog));
        DCFlushRange((void *)HBC_NETLOG_ADDR, sizeof(savedLog));
    }
    hbc_netlog_init(); // Connect only when HBC supplied a valid log target.
#endif
    hbc_agent_config config = {};
    config.name = "WiiXplorer NG";
    config.version = BuildRev();
    config.app_polls_exit = true;
    config.exit_grace_ms = 60000;
    config.no_network = !WX_DEBUG_BUILD;
    config.no_crash_handler = !WX_DEBUG_BUILD;
    // WiiXplorer owns physical buttons, VI pacing and device teardown.
    config.no_safety = HBC_AGENT_NO_BUTTONS | HBC_AGENT_NO_FLUSH | HBC_AGENT_NO_FRAMES;
    if (!WX_DEBUG_BUILD) config.no_safety |= HBC_AGENT_NO_STACK_GUARD | HBC_AGENT_NO_THREADS;
    config.gc_pads = true;
    config.on_save = SaveSettings;
    config.on_exit_choice = ExitChoice;
    config.on_frame = UpdateInfo;
    s32 result = hbc_agent_init(&config);
    ready = true; // A failed listener start still installed the log hook.
    if (result < 0) printf("HBC agent listener unavailable: %d\n", result);
    static const hbc_agent_item settings[] = {
        {"Save settings", NULL, SaveSettingsButton, NULL, 0},
    };
    snprintf(probes, sizeof(probes), "Level %d (%s)", WX_PROBE_LEVEL,
             WX_DEBUG_BUILD ? "debug" : "release");
    static const hbc_agent_item diagnostics[] = {
        {"MEM1 heap", mem1, NULL, NULL, 0},
        {"MEM2 heap", mem2, NULL, NULL, 0},
        {"Probes", probes, NULL, NULL, 0},
        {"Network / FTP", network, NULL, NULL, 0},
        {"Flush probes", NULL, FlushProbes, NULL,
            WX_PROBE_LEVEL ? 0u : HBC_AGENT_ITEM_DISABLED},
    };
    hbc_agent_set_slot_menu(0, "Settings", "WiiXplorer settings", settings, 1);
    hbc_agent_set_slot_menu(1, "Diagnostics", "WiiXplorer diagnostics", diagnostics, 5);
    UpdateInfo(NULL);
}
void HbcAgentShutdown()
{
    if (!ready) return;
    hbc_agent_shutdown();
#if WX_DEBUG_BUILD
    hbc_netlog_close();
#endif
    ready = false;
}
bool HbcAgentExitRequested() { return ready && hbc_agent_exit_requested(); }
bool HbcAgentHomePending() { return ready && hbc_agent_home_pending(); }
void HbcAgentHome() { if (ready) Video_ShowHbcHome(); }
