/* Minimal libogc/Dolphin loader regression: no WiiXplorer or HBC SDK. */
#include <gccore.h>
#include <stdlib.h>

int main(void)
{
    VIDEO_Init();
    VIDEO_WaitVSync();
    VIDEO_WaitVSync();
    exit(0);
}
