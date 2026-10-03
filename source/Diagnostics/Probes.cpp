/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "Probes.h"
#if WX_PROBE_LEVEL > 0
#include <gccore.h>
#include <ogc/machine/processor.h>
#include <ogc/lwp_watchdog.h>
#include <stdio.h>

// Fixed storage; updates are bounded and safe from worker/interrupt contexts.
// Only the main thread flushes, after presentation or before device teardown.
struct Sample { uint64_t count, timed_count, total_us, max_us, value; };
static Sample samples[5][3];
static unsigned sequence;
static unsigned written;
uint64_t wx_probe_begin(void) { return gettime(); }
void wx_probe_record(unsigned group, unsigned level, uint64_t start, uint32_t value)
{
    if (group >= 5 || level < 1 || level > WX_PROBE_LEVEL) return;
    uint64_t duration = start ? ticks_to_microsecs(gettime() - start) : 0;
    u32 irq = IRQ_Disable();
    Sample &s = samples[group][level-1];
    ++s.count;
    if (start) ++s.timed_count;
    s.total_us += duration;
    if (duration > s.max_us) s.max_us = duration;
    s.value += value;
    IRQ_Restore(irq);
}
void wx_probe_flush(void)
{
    // Cap each boot's output at 1 MiB. Retain counters for GDB if no SD is mounted.
    if (written >= 1024*1024) return;
    FILE *f = fopen("sd:/apps/WiiXplorer/probes.csv", sequence ? "a" : "w");
    if (!f) return;
    Sample snapshot[5][3];
    u32 irq = IRQ_Disable();
    __builtin_memcpy(snapshot, samples, sizeof(samples));
    __builtin_memset(samples, 0, sizeof(samples));
    IRQ_Restore(irq);
    if (!sequence) written += fprintf(f, "window,group,level,count,timed_count,total_us,max_us,value\n");
    static const char *names[] = {"cpu", "gpu", "threads", "io", "network"};
    for (unsigned g=0; g<5; ++g)
        for (unsigned l=0; l<WX_PROBE_LEVEL; ++l) {
            const Sample &s = snapshot[g][l];
            if (s.count) {
                int n = fprintf(f, "%u,%s,%u,%llu,%llu,%llu,%llu,%llu\n", sequence,
                    names[g], l+1, s.count, s.timed_count, s.total_us, s.max_us, s.value);
                if (n > 0) written += n;
            }
        }
    ++sequence;
    fclose(f);
}
#endif
