#pragma once
#if WX_DEBUG_BUILD
#include <stddef.h>
// Explicit debug-only test paths. No test configuration is read in release.
enum DebugBenchOption { BenchMemory, BenchArchive, BenchArchiveOutput, BenchCopy, BenchStorage, BenchStorageReport, BenchMedia, BenchFeatures, BenchOptions };
struct DebugBenchArguments { char paths[BenchOptions][768]; };
bool DebugBenchArgument(DebugBenchArguments &args,const char *line);
bool DebugBenchFile(DebugBenchArguments &args,const char *file);
#endif
