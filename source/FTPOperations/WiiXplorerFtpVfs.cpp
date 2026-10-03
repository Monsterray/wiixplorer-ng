/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "FtpsrvConfig.h"
#include "ftpsrv/ftpsrv_vfs.h"
#include "DeviceControls/DeviceHandler.hpp"
#include "Settings.h"
#include <limits.h>
#include <time.h>
extern "C" int wx_ftp_stopping(void);

namespace {
const uint64_t MaxUpload = UINT64_C(8)*1024*1024*1024;
bool available(int dev) {
    return dev >= 0 && dev < MAXDEVICES &&
        (dev != NAND || Settings.MountISFS) && DeviceHandler::Instance()->IsInserted(dev);
}
bool writable(int dev) {
    return available(dev) && dev != DVD && dev != NAND;
}
int fail(int error) { errno = error; return -1; }
/* Normalize virtual components before selecting a mounted device. No physical
 * path or arbitrary devoptab prefix supplied by a client reaches stdio. */
int resolve(const char *path, char *out, bool write) {
    if (!path || path[0] != '/' || strlen(path) >= 992) return fail(ENAMETOOLONG);
    char canonical[1024] = "";
    size_t used = 0;
    const char *p = path;
    while (*p) {
        while (*p == '/') ++p;
        const char *start = p;
        while (*p && *p != '/') {
            unsigned char c = *p++;
            if (c < 32 || c == 127 || c == ':' || c == '\\') return fail(EINVAL);
        }
        size_t n = p-start;
        if (!n || (n == 1 && start[0] == '.')) continue;
        if (n == 2 && !memcmp(start, "..", 2)) {
            while (used && canonical[used-1] != '/') --used;
            if (used) --used;
            canonical[used] = 0;
        } else {
            canonical[used++] = '/';
            memcpy(canonical+used, start, n); used += n; canonical[used] = 0;
        }
    }
    if (!used) { out[0] = 0; return write ? fail(EROFS) : MAXDEVICES; }
    const char *name = canonical+1;
    const char *slash = strchr(name, '/');
    size_t n = slash ? (size_t)(slash-name) : strlen(name);
    for (int dev = 0; dev < MAXDEVICES; ++dev) {
        if (strlen(DeviceName[dev]) != n || memcmp(name, DeviceName[dev], n)) continue;
        if (!available(dev)) return fail(ENODEV);
        if (write && !writable(dev)) return fail(EROFS);
        snprintf(out, 1024, "%s:%s", DeviceName[dev], slash ? slash : "/");
        if (write && (!slash || !slash[1])) return fail(EROFS);
        return dev;
    }
    return fail(ENOENT);
}
void rootstat(struct stat *st) { memset(st, 0, sizeof(*st)); st->st_mode = S_IFDIR|0555; st->st_nlink = 1; }
int copy_original(FtpVfsFile *f) {
    FILE *old = fopen(f->destination, "rb");
    if (!old) return errno == ENOENT ? 0 : -1;
    char buf[4096];
    int rc = 0;
    const time_t started = time(NULL);
    while (!feof(old)) {
        if (wx_ftp_stopping() || difftime(time(NULL),started) >= 4*60*60) { rc = fail(ECANCELED); break; }
        if (!writable(f->device)) { rc = fail(ENODEV); break; }
        size_t n = fread(buf, 1, sizeof(buf), old);
        if (ferror(old) || f->written+n > MaxUpload || fwrite(buf, 1, n, f->file) != n) { rc = fail(EIO); break; }
        f->written += n;
    }
    if (fclose(old)) rc = -1;
    return rc;
}
}
extern "C" {
int ftp_vfs_open(FtpVfsFile *f, const char *path, FtpVfsOpenMode mode) {
    memset(f, 0, sizeof(*f));
    f->device = resolve(path, f->destination, mode != FtpVfsOpenMode_READ);
    if (f->device < 0) return -1;
    if (f->device == MAXDEVICES) return fail(EISDIR);
    struct stat st;
    if (stat(f->destination, &st) == 0 && !S_ISREG(st.st_mode)) return fail(EISDIR);
    if (mode == FtpVfsOpenMode_READ) {
        f->file = fopen(f->destination, "rb");
    } else {
        f->writing = 1;
        if (wx_transfer_begin(&f->stage, f->destination)) return -1;
        f->file = fopen(f->stage.staged, "wb+");
        if (!f->file) { wx_transfer_abort(&f->stage); return -1; }
        if (mode == FtpVfsOpenMode_APPEND && copy_original(f)) { ftp_vfs_close(f); return -1; }
    }
    return f->file ? 0 : -1;
}
int ftp_vfs_read(FtpVfsFile *f, void *buf, size_t size) {
    if (!f->file || !available(f->device)) return fail(ENODEV);
    size_t n = fread(buf, 1, size, f->file);
    return ferror(f->file) ? -1 : (int)n;
}
int ftp_vfs_write(FtpVfsFile *f, const void *buf, size_t size) {
    if (!f->file || !writable(f->device)) return fail(EROFS);
    if (size > MaxUpload-f->written) return fail(EFBIG);
    size_t n = fwrite(buf, 1, size, f->file);
    f->written += n;
    return n == size ? (int)n : fail(EIO);
}
int ftp_vfs_seek(FtpVfsFile *f, const void *, size_t, size_t off) {
    if (!f->file || off > LONG_MAX) return fail(EINVAL);
    if (f->writing && off && !f->written) {
        if (copy_original(f) || off > f->written) return fail(EINVAL);
    }
    return fseek(f->file, (long)off, SEEK_SET);
}
int ftp_vfs_finish(FtpVfsFile *f, int success) {
    int rc = 0;
    if (f->file) { rc = fclose(f->file); f->file = NULL; }
    if (f->writing) {
        if (success && !rc && writable(f->device))
            rc = wx_transfer_publish(&f->stage, f->stage.staged, f->destination);
        else if (success && !rc) rc = fail(EROFS);
        wx_transfer_abort(&f->stage);
    }
    memset(f, 0, sizeof(*f));
    return rc;
}
int ftp_vfs_close(FtpVfsFile *f) { return ftp_vfs_finish(f, 0); }
int ftp_vfs_isfile_open(FtpVfsFile *f) { return f->file != NULL; }
int ftp_vfs_opendir(FtpVfsDir *d, const char *path) {
    memset(d, 0, sizeof(*d)); char physical[1024];
    d->device = resolve(path, physical, false);
    if (d->device < 0) return -1;
    if (d->device == MAXDEVICES) { d->root = 1; return 0; }
    d->dir = opendir(physical); return d->dir ? 0 : -1;
}
const char *ftp_vfs_readdir(FtpVfsDir *d, FtpVfsDirEntry *entry) {
    if (d->root) {
        while (d->next < MAXDEVICES) {
            int dev = d->next++;
            if (available(dev)) { snprintf(entry->name, sizeof(entry->name), "%s", DeviceName[dev]); return entry->name; }
        }
        errno = 0; return NULL;
    }
    if (!d->dir || !available(d->device)) { errno = ENODEV; return NULL; }
    errno = 0;
    struct dirent *e = readdir(d->dir);
    if (!e) return NULL;
    if (strlen(e->d_name) >= sizeof(entry->name)) { errno = ENAMETOOLONG; return NULL; }
    snprintf(entry->name, sizeof(entry->name), "%s", e->d_name); return entry->name;
}
int ftp_vfs_dirlstat(FtpVfsDir *, const FtpVfsDirEntry *, const char *path, struct stat *st) { return ftp_vfs_stat(path, st); }
int ftp_vfs_closedir(FtpVfsDir *d) { int rc = d->dir ? closedir(d->dir) : 0; memset(d, 0, sizeof(*d)); return rc; }
int ftp_vfs_isdir_open(FtpVfsDir *d) { return d->dir || d->root; }
int ftp_vfs_stat(const char *path, struct stat *st) {
    char physical[1024]; int dev = resolve(path, physical, false);
    if (dev < 0) return -1;
    if (dev == MAXDEVICES) { rootstat(st); return 0; }
    return stat(physical, st);
}
int ftp_vfs_lstat(const char *path, struct stat *st) { return ftp_vfs_stat(path, st); }
int ftp_vfs_mkdir(const char *path) { char p[1024]; return resolve(path,p,true)<0 ? -1 : mkdir(p,0777); }
int ftp_vfs_unlink(const char *path) { char p[1024]; return resolve(path,p,true)<0 ? -1 : unlink(p); }
int ftp_vfs_rmdir(const char *path) { char p[1024]; return resolve(path,p,true)<0 ? -1 : rmdir(p); }
int ftp_vfs_rename(const char *src, const char *dst) {
    char a[1024], b[1024]; int da = resolve(src,a,true), db = resolve(dst,b,true);
    if (da < 0 || db < 0) return -1;
    return da != db ? fail(EXDEV) : rename(a,b);
}
int ftp_vfs_readlink(const char *, char *, size_t) { return fail(ENOSYS); }
const char *ftp_vfs_getpwuid(const struct stat *) { return "wii"; }
const char *ftp_vfs_getgrgid(const struct stat *) { return "wii"; }
}
