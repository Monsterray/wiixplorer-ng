/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef WX_ARCHIVE_SAFETY_H
#define WX_ARCHIVE_SAFETY_H
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include "FileOperations/TransferFile.h"

// Defensive metadata limits, not limits on streamed file payloads.
#define WX_ARCHIVE_PATH 768
#define WX_ARCHIVE_DEPTH 32
#define WX_ARCHIVE_ITEMS 32768
#define WX_ARCHIVE_METADATA (8u*1024u*1024u)
#ifdef __cplusplus
extern "C" {
#endif
static inline uint32_t wx_archive_be32(const unsigned char *p) { return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3]; }
static inline uint16_t wx_archive_be16(const unsigned char *p) { return ((uint16_t)p[0]<<8)|p[1]; }
int wx_archive_cancelled(void);
size_t wx_archive_memory_budget(void);
int wx_archive_member(const char *name);
int wx_archive_path(char *out,size_t capacity,const char *root,const char *name,int withpath);
int wx_archive_lstat(const char *path,struct stat *st);
int wx_archive_directory(const char *path);
int wx_archive_space(const char *root,uint64_t bytes);
int wx_archive_representable(const char *root,uint64_t bytes);
#ifdef __cplusplus
}

#include "ArchiveStruct.h"
class ArchiveOutput {
public:
    ArchiveOutput(): file(NULL), ready(false) { memset(&transfer,0,sizeof(transfer)); }
    ~ArchiveOutput() { if(file) fclose(file); if(ready) wx_transfer_abort(&transfer); }
    bool Begin(const char *root,const char *name,bool withpath,bool open=true);
    bool Commit(); // Caller must also validate backend CRC/close before commit.
    FILE *file;
    wx_transfer_file transfer;
private:
    bool ready;
    char destination[WX_ARCHIVE_PATH];
};

template<class T> bool ArchivePreflight(T &archive,const char *root) {
    uint64_t total=0;
    if(archive.GetItemCount()>WX_ARCHIVE_ITEMS) return false;
    char path[WX_ARCHIVE_PATH];
    for(unsigned i=0;i<archive.GetItemCount();++i) {
        if(wx_archive_cancelled()) return false;
        ArchiveFileStruct *f=archive.GetFileStruct(i);
        if(!f || !wx_archive_path(path,sizeof(path),root,f->filename,true)) return false;
        if(!f->isdir) { if(!wx_archive_representable(root,f->length) || f->length>UINT64_MAX-total) return false; total+=f->length; }
    }
    return wx_archive_space(root,total);
}
#endif
#endif
