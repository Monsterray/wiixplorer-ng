#pragma once
#include <stddef.h>
#if WX_DEBUG_BUILD
void RunCopyBenchmark(const char *directory);
void RunStorageBenchmark(const char *directory, const char *reportDirectory = NULL);
void RunArchiveValidation(const char *directory, const char *usbRoot = NULL);
void MediaCapturePixel();
void RunMediaValidation(const char *directory);
void RunMemoryBenchmark(const char *directory);
#endif
