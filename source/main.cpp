 /************************************************************************************************************************************************
 * \mainpage WiiXplorer
 *
 * \section sec_intro Introduction
 *
 * WiiXplorer is a multi-device file explorer for the Wii made with a customized libwiigui as base for the GUI.
 * It has several additional features to execute various of filetypes like on an actual browser/explorer.
 * <p>
 * It was created and is developed by Dimok. Some features of the project were contributed/developed by R-win and Dude.
 * <p>
 * The graphical design and the required artwork for that were/are made by NeoRame.
 * <p>
 * WiiXplorer is written mainly in C++ and makes use of sevaral open-source C/C++ libraries.
 * <p>
 * \section sec_special_thanks Special thanks:
 * Dj Skual, kavid and all translators<br>
 * Tantric for his tool libwiigui<br>
 * Armin Tamzarian for FreeTypeGX<br>
 * The libogc/devkitPro Team<br>
 *
 * \section sec_license License
 *
 * The WiiXplorer source code is distributed under the GNU General Public License v3.
 *
 * \section sec_contact Contact
 *
 * If you have any suggestions, questions, or comments regarding the source code or the application feel free to e-mail me at dimok789@gmail.com.
 *************************************************************************************************************************************************/
#include "Controls/Application.h"
#include "VideoOperations/video.h"
#include "sys.h"
#include "Diagnostics/HbcAgent.h"
#if WX_DEBUG_BUILD
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include "Diagnostics/TransferBench.h"

static u32 ParseSmokeFrames(const char *text)
{
	if (!text || text[0] < '0' || text[0] > '9') return 0;
	char *end;
	unsigned long value = strtoul(text, &end, 10);
	while (*end && isspace((unsigned char)*end)) ++end;
	if (*end) return 0;
	return value > 0 && value <= 36000 ? value : 0;
}

static u32 SmokeFrames(int argc, char **argv)
{
	for (int i=1; i<argc; ++i)
		if (!strncmp(argv[i], "--smoke-frames=", 15)) return ParseSmokeFrames(argv[i]+15);
	char text[32] = {};
	FILE *f = fopen("sd:/apps/WiiXplorer/smoke-frames.txt", "r");
	if (!f) return 0;
	fgets(text, sizeof(text), f);
	fclose(f);
	return ParseSmokeFrames(text);
}
#endif

int main(int argc UNUSED, char *argv[] UNUSED)
{
#if WX_DEBUG_BUILD
    char memoryDirectory[768]={};
    for(int i=1;i<argc;++i)
        if(!strncmp(argv[i],"--memory-bench=",15) && strlen(argv[i]+15)<sizeof(memoryDirectory))
            memcpy(memoryDirectory,argv[i]+15,strlen(argv[i]+15)+1);
#endif
	HbcAgentPrepare();
	__exception_setreload(30);
	// Initialize video before anything else as otherwise green stripes are produced, need to figure out why...
	InitVideo();

	Application::Instance()->init();
	Application::Instance()->show();
#if WX_DEBUG_BUILD
    if(memoryDirectory[0]) RunMemoryBenchmark(memoryDirectory);
	Application::Instance()->SetSmokeFrames(SmokeFrames(argc, argv));
	for (int i=1; i<argc; ++i)
		if (!strncmp(argv[i], "--copy-bench=", 13)) RunCopyBenchmark(argv[i]+13);

		else if (!strncmp(argv[i], "--storage-bench=", 16)) {
            const char *report=NULL;
            for (int j=1;j<argc;++j)
                if (!strncmp(argv[j],"--storage-report=",17)) report=argv[j]+17;
            RunStorageBenchmark(argv[i]+16,report);
        }
#endif
	Application::Instance()->exec();

	Sys_ExecuteExit();
	return 0;
}
