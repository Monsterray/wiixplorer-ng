/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef WX_PROBES_H
#define WX_PROBES_H
#include <stdint.h>
#ifndef WX_PROBE_LEVEL
#define WX_PROBE_LEVEL 0
#define WX_PROBE_CPU 0
#define WX_PROBE_GPU 0
#define WX_PROBE_THREADS 0
#define WX_PROBE_IO 0
#define WX_PROBE_NETWORK 0
#endif
#ifdef __cplusplus
extern "C" {
#endif
#if WX_PROBE_LEVEL > 0
uint64_t wx_probe_begin(void);
void wx_probe_record(unsigned group, unsigned level, uint64_t start, uint32_t value);
void wx_probe_flush(void);
#define WX_PROBE(group, level, value) do { if (WX_PROBE_##group && WX_PROBE_LEVEL >= (level)) wx_probe_record(WX_GROUP_##group, level, 0, value); } while (0)
#else
#define WX_PROBE(group, level, value) ((void)0)
#define wx_probe_flush() ((void)0)
#endif
#define WX_GROUP_CPU 0
#define WX_GROUP_GPU 1
#define WX_GROUP_THREADS 2
#define WX_GROUP_IO 3
#define WX_GROUP_NETWORK 4
#ifdef __cplusplus
}
#if WX_PROBE_LEVEL >= 2
class WxProbeScope {
    unsigned group;
    uint64_t start;
public:
    explicit WxProbeScope(unsigned g): group(g), start(g < 5 ? wx_probe_begin() : 0) {}
    ~WxProbeScope() { if (group < 5) wx_probe_record(group, 2, start, 0); }
};
#define WX_SCOPE(group) WxProbeScope wx_scope(WX_PROBE_##group && WX_PROBE_LEVEL >= 2 ? WX_GROUP_##group : 5)
#else
#define WX_SCOPE(group) ((void)0)
#endif
#endif
#endif
