/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef WX_TRANSFER_FILE_H
#define WX_TRANSFER_FILE_H
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>

/* Reserve a private directory on the destination filesystem. Never truncate
 * an existing file, including another transfer's temporary file. */
typedef struct {
    char directory[1024], staged[1040], previous[1040];
} wx_transfer_file;

static inline int wx_transfer_begin(wx_transfer_file *t, const char *destination)
{
    unsigned i;
    memset(t, 0, sizeof(*t));
    if (!destination || strlen(destination) > sizeof(t->directory) - 32)
        return -1;
    for (i = 0; i < 16; ++i) {
        snprintf(t->directory, sizeof(t->directory), "%s.wx-transfer-%u", destination, i);
        if (mkdir(t->directory, 0700) == 0) {
            snprintf(t->staged, sizeof(t->staged), "%s/data", t->directory);
            snprintf(t->previous, sizeof(t->previous), "%s/previous", t->directory);
            return 0;
        }
        if (errno != EEXIST) break;
    }
    t->directory[0] = 0;
    return -1;
}

static inline void wx_transfer_abort(wx_transfer_file *t)
{
    if (!t->directory[0]) return;
    remove(t->staged);
    /* If rollback failed, retain previous for recovery. Never delete it. */
    rmdir(t->directory);
}

/* FAT and some remote filesystems cannot rename over an existing file.
 * Keep the previous destination until publication succeeds. This is safe
 * against reported I/O failures; the two renames are not power-loss atomic. */
static inline int wx_transfer_publish(wx_transfer_file *t, const char *source,
                                      const char *destination)
{
    struct stat st;
    int had_previous = stat(destination, &st) == 0;
    if (!had_previous && errno != ENOENT) return -1;
    if (had_previous && S_ISDIR(st.st_mode)) return -1;
    if (had_previous && rename(destination, t->previous) != 0) return -1;
    if (rename(source, destination) != 0) {
        if (had_previous) rename(t->previous, destination);
        return -1;
    }
    if (had_previous) remove(t->previous);
    rmdir(t->directory);
    return 0;
}
#endif
