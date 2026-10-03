/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef WX_FTP_VFS_H
#define WX_FTP_VFS_H
#include <stdio.h>
#include <dirent.h>
#include <stdint.h>
#include "FileOperations/TransferFile.h"
struct FtpVfsFile {
    FILE *file;
    wx_transfer_file stage;
    char destination[1024];
    uint64_t written;
    int device;
    int writing;
};
struct FtpVfsDir { DIR *dir; int root, next, device; };
struct FtpVfsDirEntry { char name[256]; };
/* close() always aborts a staged upload; finish() publishes only on success. */
int ftp_vfs_finish(struct FtpVfsFile *file, int success);
#endif
