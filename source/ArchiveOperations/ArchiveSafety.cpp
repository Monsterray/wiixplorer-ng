/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "ArchiveStruct.h"
#include "ArchiveSafety.h"
#include <stdlib.h>
#include <limits.h>
#include <limits>
#include "Controls/Application.h"
#include "Prompts/ProgressWindow.h"
#include <sys/statvfs.h>
#if defined(GEKKO)
#include <malloc.h>
#include "Memory/mem2.h"
#include "DeviceControls/DeviceHandler.hpp"
#include <sys/iosupport.h>
#endif

int wx_archive_cancelled(void)
{
    return Application::isClosing() || ProgressWindow::Instance()->IsCanceled();
}

size_t wx_archive_memory_budget(void)
{
    size_t limit=16u*1024u*1024u;
#if defined(GEKKO)
    uint64_t available=(uint64_t)MEM2_freesize()+mallinfo().fordblks;
    if(available/2<limit) limit=(size_t)(available/2);
#endif
    return limit; // Leave at least half of currently free application heaps.
}

int wx_archive_member(const char *name)
{
    if(!name) return 0;
    size_t length=strnlen(name,WX_ARCHIVE_PATH);
    if(!length || length>=WX_ARCHIVE_PATH || name[0]=='/') return 0;
    unsigned depth=0;
    const char *component=name;
    for(const char *p=name;;++p) {
        unsigned char c=*p;
        if(c=='\\' || c==':' || (c && (c<32 || c==127))) return 0;
        if(c=='/' || !c) {
            size_t n=p-component;
            if(!n || n>255 || component[n-1]==' ' || component[n-1]=='.' || (n==1 && component[0]=='.') ||
               (n==2 && component[0]=='.' && component[1]=='.') || ++depth>WX_ARCHIVE_DEPTH) return 0;
            if(!c || !p[1]) return 1; // One trailing slash is a directory marker.
            component=p+1;
        }
    }
}

int wx_archive_path(char *out,size_t capacity,const char *root,const char *name,int withpath)
{
    if(!out || !capacity || !root || !root[0] || !wx_archive_member(name)) return 0;
    size_t n=strnlen(root,WX_ARCHIVE_PATH);
    if(n>=WX_ARCHIVE_PATH) return 0;
    while(n>1 && root[n-1]=='/' && root[n-2]!=':') --n;
    // Validate the selected root too, allowing only its initial device prefix.
    const char *base=root;
    const char *colon=strchr(root,':');
    if(colon) {
        if(colon==root || colon[1]!='/') return 0;
        for(const char *p=root;p<colon;++p) if(!((*p>='a' && *p<='z') || (*p>='A' && *p<='Z') || (*p>='0' && *p<='9') || *p=='_')) return 0;
        base=colon+2;
    }
    else if(*base=='/') ++base;
    if(strcmp(root,".") && strcmp(root,"./") && *base && !wx_archive_member(base)) return 0;
    size_t m=strlen(name);
    if(name[m-1]=='/') --m;
    const char *member=name;
    if(!withpath) {
        for(size_t i=0;i<m;++i) if(name[i]=='/') member=name+i+1;
        m-=member-name;
    }
    int result=snprintf(out,capacity,"%.*s%s%.*s",(int)n,root,root[n-1]=='/' ? "" : "/",(int)m,member);
    return result>0 && (size_t)result<capacity && (size_t)result<WX_ARCHIVE_PATH;
}

int wx_archive_lstat(const char *path,struct stat *st)
{
#if defined(GEKKO)
    const devoptab_t *device=GetDeviceOpTab(path);
    if(device && device->lstat_r) return lstat(path,st);
    // FAT has no symlinks. Its current devoptab lacks lstat, so stat is safe
    // only after confirming the mounted filesystem (never by drive name).
    const char *fs=DeviceHandler::PathToFSName(path);
    if(fs && !strncmp(fs,"FAT",3)) return stat(path,st);
    errno=ENOTSUP; return -1;
#else
    return lstat(path,st);
#endif
}

// Fail closed on links and non-directory ancestors. Walk rather than using
// CreateSubfolder(), which follows stat() links. No archive may create links.
int wx_archive_directory(const char *path)
{
    if(!path || !path[0] || strlen(path)>=WX_ARCHIVE_PATH) return 0;
    char copy[WX_ARCHIVE_PATH]; strcpy(copy,path);
    size_t start=copy[0]=='/' ? 1 : 0;
    char *colon=strchr(copy,':');
    if(colon) { if(colon[1]!='/') return 0; start=colon-copy+2; }
    for(size_t i=start;;++i) {
        if(copy[i]!='/' && copy[i]) continue;
        char saved=copy[i]; copy[i]=0;
        struct stat st;
        int result=wx_archive_lstat(copy,&st);
        if(result && errno==ENOENT) {
            if(mkdir(copy,0700)!=0 && errno!=EEXIST) return 0;
            result=wx_archive_lstat(copy,&st);
        }
        if(result || !S_ISDIR(st.st_mode)) return 0;
        copy[i]=saved;
        if(!saved) return 1;
    }
}

int wx_archive_representable(const char *root,uint64_t bytes)
{
    if(bytes>(uint64_t)std::numeric_limits<off_t>::max()) return 0;
#if defined(GEKKO)
    const char *fs=DeviceHandler::PathToFSName(root);
    if(fs && !strncmp(fs,"FAT",3) && bytes>UINT32_MAX) return 0;
#else
    (void)root;
#endif
    return 1;
}

int wx_archive_space(const char *root,uint64_t bytes)
{
    if(!wx_archive_directory(root)) return 0;
    struct statvfs st;
    if(statvfs(root,&st)!=0) return 0;
    uint64_t unit=st.f_frsize ? st.f_frsize : st.f_bsize;
    if(!unit) return 0;
    return bytes/unit + (bytes%unit!=0) <= st.f_bavail;
}

bool ArchiveOutput::Begin(const char *root,const char *name,bool withpath,bool open)
{
    if(ready || !wx_archive_path(destination,sizeof(destination),root,name,withpath)) return false;
    char parent[WX_ARCHIVE_PATH]; strcpy(parent,destination);
    char *slash=strrchr(parent,'/'); if(!slash) return false;
    slash[1]=0;
    if(!wx_archive_directory(parent)) return false;
    struct stat st;
    if(wx_archive_lstat(destination,&st)==0) { if(!S_ISREG(st.st_mode)) return false; }
    else if(errno!=ENOENT) return false;
    if(wx_transfer_begin(&transfer,destination)!=0) return false;
    ready=true;
    if(open) { file=fopen(transfer.staged,"wb"); if(!file) return false; }
    return true;
}

bool ArchiveOutput::Commit()
{
    if(!ready || wx_archive_cancelled()) return false;
    if(file) { FILE *closing=file; file=NULL; if(fclose(closing)!=0) return false; }
    char parent[WX_ARCHIVE_PATH]; strcpy(parent,destination);
    strrchr(parent,'/')[1]=0;
    if(!wx_archive_directory(parent)) return false;
    struct stat st;
    if(wx_archive_lstat(destination,&st)==0) { if(!S_ISREG(st.st_mode)) return false; }
    else if(errno!=ENOENT) return false;
    if(wx_archive_cancelled() || wx_transfer_publish(&transfer,transfer.staged,destination)!=0) return false;
    ready=false;
    return true;
}
