 /***************************************************************************
 * Copyright (C) 2009
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
 * networkops.cpp
 *
 * Network operations
 * for Wii-Xplorer 2009
 ***************************************************************************/
#include <stdio.h>
#include <malloc.h>
#include "Settings.h"
#include <string.h>
#include <ogcsys.h>
#include <ogc/machine/processor.h>

#include "FTPOperations/FTPServer.h"
#include "http.h"
#include "networkops.h"
#include "Diagnostics/Probes.h"
#include <atomic>
#include <ogc/semaphore.h>
#include <hbc_agent.h>
static std::atomic_bool networkinit(false);
static char IP[16];
static u8 * ThreadStack = NULL;
static bool firstRun = false;

static lwp_t networkthread = LWP_THREAD_NULL;
static std::atomic_bool networkHalt(true);
static std::atomic_bool exitRequested(false);
static sem_t networkWake;

/****************************************************************************
 * Initialize_Network
 ***************************************************************************/
void Initialize_Network(void)
{
	WX_SCOPE(NETWORK);
	WX_PROBE(NETWORK, 1, 1);
	if(networkinit)
		return;
	// The agent may already be bringing IOS networking up. Never start it twice.
	s32 agentNetwork = hbc_agent_net_wait(20000);
    if (agentNetwork == -ETIMEDOUT) return;
    // if_config also initializes libogc's standard BSD socket adapter.
    // The bounded agent wait above prevents overlapping network startup.

	s32 result;

	result = if_config(IP, NULL, NULL, true, 20);

	if(result < 0) {
		networkinit = false;
		return;
	}

	networkinit = true;
	return;
}

/****************************************************************************
 * DeInit_Network
 ***************************************************************************/
void DeInit_Network(void)
{
	net_deinit();
}
/****************************************************************************
 * Check if network was initialised
 ***************************************************************************/
bool IsNetworkInit(void)
{
	return networkinit;
}

/****************************************************************************
 * Get network IP
 ***************************************************************************/
char * GetNetworkIP(void)
{
	return IP;
}

/****************************************************************************
 * HaltNetwork
 ***************************************************************************/
void HaltNetworkThread()
{
    networkHalt = true;
}

void ResumeNetworkThread()
{
    networkHalt = false;
    if (networkthread != LWP_THREAD_NULL) LWP_SemPost(networkWake);
}

/*********************************************************************************
 * Networkthread for background network initialize with idle prio
 *********************************************************************************/
static void * networkinitcallback(void *arg __attribute__((unused)))
{
	while(!exitRequested)
	{
		if(networkHalt)
		{
			LWP_SemWait(networkWake);
			usleep(100);
			continue;
		}

		if(!networkinit)
			Initialize_Network();

		if(!firstRun)
		{
			if (Settings.AutoConnect) {
				ConnectSMBShare();
				ConnectFTP();
				ConnectNFS();
			}
			if(Settings.FTPServer.AutoStart)
				FTPServer::Instance()->StartupFTP();

			LWP_SetThreadPriority(networkthread, 0);
			firstRun = true;
		}

		// HBC-Reborn owns the Wiiload/developer port; do not start a second listener.
		usleep(200000);
	}
	return NULL;
}

/****************************************************************************
 * InitNetworkThread with priority 0 (idle)
 ***************************************************************************/
void InitNetworkThread()
{
	if (networkthread != LWP_THREAD_NULL) return;
	exitRequested = false;
	LWP_SemInit(&networkWake, 0, 1);
	ThreadStack = (u8 *) memalign(32, 16384);
	if(!ThreadStack)
		return;

	LWP_CreateThread (&networkthread, networkinitcallback, NULL, ThreadStack, 16384, 30);
	ResumeNetworkThread();
}

/****************************************************************************
 * ShutdownThread
 ***************************************************************************/
void ShutdownNetworkThread()
{
	exitRequested = true;

	if(networkthread != LWP_THREAD_NULL)
	{
		ResumeNetworkThread();
		LWP_JoinThread (networkthread, NULL);
		networkthread = LWP_THREAD_NULL;
		LWP_SemDestroy(networkWake);
	}

	if(ThreadStack)
		free(ThreadStack);
	ThreadStack = NULL;
}
