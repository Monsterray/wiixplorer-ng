#pragma once
#include <stddef.h>
#if WX_DEBUG_BUILD
void RunCopyBenchmark(const char *directory);
void RunStorageBenchmark(const char *directory, const char *reportDirectory = NULL);
void RunMemoryBenchmark(const char *directory);
#endif
