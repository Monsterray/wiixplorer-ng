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
#include "Diagnostics/DebugLaunch.h"

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
    DebugBenchArguments bench={};
    for(int i=1;i<argc;++i) DebugBenchArgument(bench,argv[i]);
#endif
	HbcAgentPrepare();
	__exception_setreload(30);
	// Initialize video before anything else as otherwise green stripes are produced, need to figure out why...
	InitVideo();

	Application::Instance()->init();
	Application::Instance()->show();
#if WX_DEBUG_BUILD
    DebugBenchFile(bench,"sd:/apps/WiiXplorer/bench.cfg");
    if(bench.paths[BenchFeatures][0]) RunFeatureValidation(bench.paths[BenchFeatures]);
    if(bench.paths[BenchMedia][0]) RunMediaValidation(bench.paths[BenchMedia]);
    if(bench.paths[BenchMemory][0]) RunMemoryBenchmark(bench.paths[BenchMemory]);
    if(bench.paths[BenchArchive][0]) RunArchiveValidation(bench.paths[BenchArchive],bench.paths[BenchArchiveOutput][0] ? bench.paths[BenchArchiveOutput] : NULL);
    Application::Instance()->SetSmokeFrames(SmokeFrames(argc, argv));
    if(bench.paths[BenchCopy][0]) RunCopyBenchmark(bench.paths[BenchCopy]);
    if(bench.paths[BenchStorage][0]) RunStorageBenchmark(bench.paths[BenchStorage],bench.paths[BenchStorageReport][0] ? bench.paths[BenchStorageReport] : NULL);
#endif
	Application::Instance()->exec();

	Sys_ExecuteExit();
	return 0;
}
