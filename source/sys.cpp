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
#include "network/networkops.h"
#include "Diagnostics/HbcAgent.h"
#include "Prompts/PromptWindows.h"
#include "Prompts/ProgressWindow.h"
#include "Launcher/Channels.h"
#include "BootHomebrew/BootHomebrewTask.h"
#include "Controls/Application.h"
#include "Controls/Clipboard.h"
#include "Controls/Taskbar.h"
#include "DeviceControls/DeviceHandler.hpp"
#include "FTPOperations/FTPServer.h"
#include "Memory/mem2.h"
#include "VideoOperations/video.h"
#include "SoundOperations/SoundHandler.hpp"
#include "SoundOperations/MusicPlayer.h"
#include "TextOperations/FontSystem.h"
#include "FileOperations/fileops.h"
#include "DiskOperations/di2.h"
#include "Tools/tools.h"
#include "audio.h"
#include "input.h"
#include "sys.h"
#include "Controls/ThreadedTaskHandler.hpp"
#include "Controls/ExternalKeyboard.h"
#include "Diagnostics/Probes.h"
#include <stdlib.h>

static bool cleanupComplete = false;
enum ExitAction { ExitLoader, ExitMenu, ExitHBC, ExitReboot, ExitPower, ExitIdle, ExitStandby };
static ExitAction exitAction = ExitLoader;
static void RequestExit(ExitAction action)
{
	exitAction = action;
	if (cleanupComplete) Sys_ExecuteExit();
	else Application::closeRequest();
}


extern "C" bool RebootApp()
{
	char filepath[MAXPATHLEN];

	if(strlen(Settings.UpdatePath) > 0 && Settings.UpdatePath[strlen(Settings.UpdatePath)-1] != '/')
		snprintf(filepath, sizeof(filepath), "%s/boot.dol", Settings.UpdatePath);
	else
		snprintf(filepath, sizeof(filepath), "%sboot.dol", Settings.UpdatePath);

	ClearArguments();
	AddBootArgument(filepath);

	BootHomebrewTask *task = new BootHomebrewTask(filepath);
	task->SetAutoRunOnLoadFinish(true);

	return true;
}

extern "C" void ExitApp()
{
	//! this should never happen, but its just in case here
	static bool bRunOnce = false;
	if(bRunOnce)
		return;
	bRunOnce = true;

    // Stop producers while GUI, audio decoders, and mounted devices still exist.
    Application::closeRequest();
    HbcAgentShutdown();
    ThreadedTaskHandler::DestroyInstance();
    ExternalKeyboard::DestroyInstance();
    ShutdownNetworkThread();
    FTPServer::DestroyInstance();
    MusicPlayer::DestroyInstance();
    if (Settings.DeleteTempPath) RemoveDirectory(Settings.TempPath);
    Settings.Save();
    Application::Instance()->quit();
    StopGX(); // Drain the GPU before releasing texture and framebuffer owners.
    ShutdownAudio(); // Stop DMA/callbacks before releasing sounds and decoders.
    Clipboard::DestroyInstance();
    Taskbar::DestroyInstance();
    ProgressWindow::DestroyInstance();
    Channels::DestroyInstance();
    Application::DestroyInstance();
    Resources::DestroyInstance();
    SoundHandler::DestroyInstance();
    wx_probe_flush();
    DeviceHandler::DestroyInstance();
	ClearFontData();
	DI2_Close();
	USB_Deinitialize();
	ShutdownPads();
	DeInit_Network();
	ISFS_Deinitialize();
	MagicPatches(0);
	cleanupComplete = true;
#if WX_DEBUG_BUILD
	SYS_Report("WiiXplorer: shutdown cleanup completed\n");
#endif
}

extern "C" void __Sys_ResetCallback(u32 UNUSED, void * UNUSED)
{
	Application::resetSystem();
}

extern "C" void __Sys_PowerCallback(void)
{
	Application::shutdownSystem();
}


extern "C" void Sys_Init(void)
{
	SYS_SetResetCallback(__Sys_ResetCallback);
	SYS_SetPowerCallback(__Sys_PowerCallback);
}

static void PerformReboot(void)
{
	ExitApp();
	STM_RebootSystem();
}

#define ShutdownToDefault	0
#define ShutdownToIdle		1
#define ShutdownToStandby	2

static void _Sys_Shutdown(int SHUTDOWN_MODE)
{
	ExitApp();

	if((CONF_GetShutdownMode() == CONF_SHUTDOWN_IDLE &&  SHUTDOWN_MODE != ShutdownToStandby) || SHUTDOWN_MODE == ShutdownToIdle) {
		s32 ret;

		ret = CONF_GetIdleLedMode();
		if(ret >= 0 && ret <= 2)
			STM_SetLedMode(ret);

		STM_ShutdownToIdle();
	} else {
		STM_ShutdownToStandby();
	}
}

static void PerformShutdown(void)
{
	_Sys_Shutdown(ShutdownToDefault);
}

static void PerformIdle(void)
{
	_Sys_Shutdown(ShutdownToIdle);
}

static void PerformStandby(void)
{
	_Sys_Shutdown(ShutdownToStandby);
}

static void PerformMenu(void)
{
	ExitApp();

	if(Settings.OverridePriiloader) {
		// Priiloader shutup
		const u32 magic = 0x50756e65;
		// This Priiloader marker is not word-aligned on PowerPC.
		memcpy((void *)0x8132fffb, &magic, sizeof(magic));
		DCFlushRange((void *)0x8132fffb, sizeof(magic));
	}

	/* Return to the Wii system menu */
	SYS_ResetSystem(SYS_RETURNTOMENU, 0, 0);
}

static void PerformLoader(void)
{
	ExitApp();

	if (IsFromHBC())
		exit(0); // libogc invokes the loader return stub.

	// Channel Version
	SYS_ResetSystem(SYS_RETURNTOMENU, 0, 0);
}

extern "C" bool IsFromHBC()
{
	if(!(*((u32*) 0x80001800)))
		return false;

	char * signature = (char *) 0x80001804;
	if(strncmp(signature, "STUBHAXX", 8) == 0)
	{
		return true;
	}

	return false;
}

#define HBC_HAXX	0x0001000148415858LL
#define HBC_JODI	0x000100014A4F4449LL
#define HBC_1_0_7	0x00010001AF1BF516LL
#define HBC_LULZ	0x000100014c554c5aLL

static void PerformHBC(void)
{
	ExitApp();
	if (IsFromHBC()) exit(0);

	WII_Initialize();

	int ret = WII_LaunchTitle(HBC_LULZ);
	if(ret < 0)
		ret = WII_LaunchTitle(HBC_1_0_7);
	if(ret < 0)
		ret = WII_LaunchTitle(HBC_JODI);
	if(ret < 0)
		ret = WII_LaunchTitle(HBC_HAXX);

	//Back to system menu if all fails
	SYS_ResetSystem(SYS_RETURNTOMENU, 0, 0);
}

extern "C" void Sys_Reboot(void) { RequestExit(ExitReboot); }
extern "C" void Sys_Shutdown(void) { RequestExit(ExitPower); }
extern "C" void Sys_ShutdownToIdle(void) { RequestExit(ExitIdle); }
extern "C" void Sys_ShutdownToStandby(void) { RequestExit(ExitStandby); }
extern "C" void Sys_LoadMenu(void) { RequestExit(ExitMenu); }
extern "C" void Sys_BackToLoader(void) { RequestExit(ExitLoader); }
extern "C" void Sys_LoadHBC(void) { RequestExit(ExitHBC); }
extern "C" void Sys_ExecuteExit(void)
{
    ExitApp();
    switch (exitAction) {
        case ExitMenu: PerformMenu(); break;
        case ExitHBC: PerformHBC(); break;
        case ExitReboot: PerformReboot(); break;
        case ExitPower: PerformShutdown(); break;
        case ExitIdle: PerformIdle(); break;
        case ExitStandby: PerformStandby(); break;
        default: PerformLoader(); break;
    }
}

extern "C" int GetIOS_Rev(u32 ios)
{
	u32 num_titles = 0, i = 0;
	u64 tid = 0;
	u64 * titles = NULL;
	s32 ret = -1;

	ret = ES_GetNumTitles(&num_titles);
	if(ret < 0)
		return -1;

	if(num_titles < 1)
		return -1;

	titles = (u64 *) memalign(32, ALIGN32(num_titles * sizeof(u64) + 32));
	if(!titles)
		return -1;

	ret = ES_GetTitles(titles, num_titles);
	if(ret < 0)
	{
		free(titles);
		return -1;
	}

	for(i=0; i < num_titles; i++)
	{
		if ((titles[i] & 0xFFFFFFFF) == ios)
		{
			tid = titles[i];
			break;
		}
	}

	free(titles);
	titles = NULL;

	if(!tid)
		return -1;

	ISFS_Initialize();

	char tmd[ISFS_MAXPATH];
	static fstats stats ATTRIBUTE_ALIGN(32);
	ret = -1;

	u32 high = (u32)(tid >> 32);
	u32 low  = (u32)(tid & 0xFFFFFFFF);

	sprintf(tmd, "/title/%08x/%08x/content/title.tmd", high, low);

	s32 fd = ISFS_Open(tmd, ISFS_OPEN_READ);
	if (fd >= 0)
	{
		if (ISFS_GetFileStats(fd, &stats) >= 0)
		{
			u32 * data = NULL;

			if (stats.file_length > 0)
				data = (u32 *) memalign(32, ALIGN32(stats.file_length));

			if (data)
			{
				if (ISFS_Read(fd, (char *) data, stats.file_length) > 0x208)
				{
					ret = ((struct _tmd *) SIGNATURE_PAYLOAD(data))->title_version;
				}
				free(data);
			}
		}
		ISFS_Close(fd);
	}

	ISFS_Deinitialize();

	return ret;
}

extern "C" bool FindTitle(u64 titleid)
{
	bool found = false;
	u32 num_titles = 0, i = 0;
	u64 * titles = NULL;
	s32 ret = 0;

	ret = ES_GetNumTitles(&num_titles);
	if(ret < 0)
		return found;

	if(num_titles < 1)
		return found;

	titles = (u64 *) memalign(32, ALIGN32(num_titles * sizeof(u64) + 32));
	if(!titles)
		return found;

	ret = ES_GetTitles(titles, num_titles);
	if(ret < 0)
	{
		free(titles);
		return found;
	}

	for(i=0; i < num_titles; i++)
	{
		if (titles[i] == titleid)
		{
			found = true;
			break;
		}
	}

	free(titles);

	return found;
}
