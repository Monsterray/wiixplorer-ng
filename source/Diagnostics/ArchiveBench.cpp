/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "TransferBench.h"
#if WX_DEBUG_BUILD
#include "ArchiveOperations/Archive.h"
#include "ArchiveOperations/ArchiveSafety.h"
#include <ogc/lwp_watchdog.h>
#include <stdio.h>
#include <string.h>
#include <zlib.h>
#include <errno.h>
#include <unistd.h>
#include <sys/stat.h>

static bool ArchiveFixture(const char *path,const char *text)
{
    FILE *f=fopen(path,"wb"); if(!f) return false;
    bool okay=fwrite(text,1,strlen(text),f)==strlen(text);
    return fclose(f)==0 && okay;
}
static bool ArchiveVerify(const char *path,u64 bytes,u32 expected)
{
    FILE *f=fopen(path,"rb"); if(!f) return false;
    u8 buffer[8192]; u64 total=0; u32 crc=crc32(0,NULL,0); size_t n;
    while((n=fread(buffer,1,sizeof(buffer),f))) {
        if(total>bytes || n>bytes-total) { fclose(f); return false; }
        total+=n; crc=crc32(crc,buffer,n);
    }
    bool okay=!ferror(f) && total==bytes && crc==expected;
    return fclose(f)==0 && okay;
}
static bool ArchiveCopyFixture(const char *source,const char *target)
{
    FILE *in=fopen(source,"rb"); if(!in) return false;
    FILE *out=fopen(target,"wb"); if(!out) { fclose(in); return false; }
    u8 buffer[8192]; size_t n; bool okay=true;
    while((n=fread(buffer,1,sizeof(buffer),in)))
        if(fwrite(buffer,1,n,out)!=n) { okay=false; break; }
    okay=okay && !ferror(in);
    if(fclose(in)!=0) okay=false;
    if(fclose(out)!=0) okay=false;
    return okay;
}
static bool ArchiveEraseFixture(const char *root,const char *member)
{
    char path[768]; if(!wx_archive_path(path,sizeof(path),root,member,true)) return false;
    struct stat st;
    if(stat(path,&st)==0) {
        if((S_ISDIR(st.st_mode) ? rmdir(path) : unlink(path))!=0) return false;
    } else if(errno!=ENOENT) return false;
    // Remove only empty parents of a known fixture, retaining unknown recovery files.
    const size_t length=strlen(root);
    char *slash;
    while((slash=strrchr(path,'/')) && (size_t)(slash-path)>length) {
        *slash=0;
        if(rmdir(path)!=0 && errno!=ENOENT && errno!=ENOTEMPTY && errno!=EEXIST) return false;
    }
    return true;
}
static bool ArchiveEmptyDirectory(const char *root,const char *member)
{
    char path[768]; struct stat st;
    return wx_archive_path(path,sizeof(path),root,member,true) && stat(path,&st)==0 && S_ISDIR(st.st_mode);
}
void RunArchiveValidation(const char *root,const char *usbRoot)
{
    // Explicit debug argument, isolated fixture root supplied by the leased
    // runner. Never enumerate or modify ordinary user archive directories.
    if(!root || strlen(root)>600 || !wx_archive_member(strchr(root,'/') ? strchr(root,'/')+1 : "") ||
       (strncmp(root,"sd:/wiixplorer-archive-",23) && strncmp(root,"usb1:/wiixplorer-archive-",25))) return;
    const char *work=root;
    if(usbRoot) {
        if(strncmp(usbRoot,"usb1:/wiixplorer-archive-",25) || strlen(usbRoot)>600 ||
           !wx_archive_member(usbRoot+6) || mkdir(usbRoot,0700)!=0) return;
        work=usbRoot; // Inputs, extraction and packing all use the mounted USB partition.
    }
    char manifest[768],report[768];
    if(!wx_archive_path(manifest,sizeof(manifest),root,"manifest",true) ||
       !wx_archive_path(report,sizeof(report),root,"archive-results.csv",true)) return;
    FILE *input=fopen(manifest,"rb"); if(!input) return;
    FILE *out=fopen(report,"wb"); if(!out) { fclose(input); return; }
    bool okay=fprintf(out,"case,result,count,microseconds,verified\n")>0;
    char line[1024],name[128],member[128]; unsigned success,count,crc; unsigned long long bytes;
    unsigned cases=0;
    while(okay && fgets(line,sizeof(line),input)) {
        if(++cases>64 || !strchr(line,'\n') || sscanf(line,"%127s %u %u %127s %llu %x",name,&success,&count,member,&bytes,&crc)!=6 ||
           !wx_archive_member(name) || !wx_archive_member(member) || success>1 || count>WX_ARCHIVE_ITEMS) { okay=false; break; }
        char source[768],dest[768],target[768];
        int joined=snprintf(dest,sizeof(dest),"%s/out-%s",work,name);
        if(joined<=0 || (size_t)joined>=sizeof(dest) || !wx_archive_path(source,sizeof(source),root,name,true) ||
           !wx_archive_directory(dest) || !wx_archive_path(target,sizeof(target),dest,member,true)) { okay=false; break; }
        if(usbRoot) {
            char copied[768];
            if(!wx_archive_path(copied,sizeof(copied),work,name,true) || !ArchiveCopyFixture(source,copied)) { okay=false; break; }
            strcpy(source,copied);
        }
        // Original targets prove CRC/parser/decode failures do not replace data.
        char parent[768]; strcpy(parent,target); strrchr(parent,'/')[1]=0;
        if(!wx_archive_directory(parent) || !ArchiveFixture(target,"original")) { okay=false; break; }
        u64 start=gettime(); ArchiveHandle archive(source);
        unsigned actualCount=archive.GetItemCount(); int result=archive.ExtractAll(dest);
        u64 elapsed=ticks_to_microsecs(gettime()-start);
        bool verified=success ? result>0 && actualCount==count && ArchiveVerify(target,bytes,crc) :
                               result<=0 && ArchiveVerify(target,8,crc32(0,(const Bytef*)"original",8));
        if(verified && success && (!strcmp(name,"good.zip") || !strcmp(name,"good.7z"))) {
            char empty[768];
            verified=ArchiveEmptyDirectory(dest,"empty") && wx_archive_path(empty,sizeof(empty),dest,"zero",true) && ArchiveVerify(empty,0,0);
        }
        if(usbRoot && verified) {
            for(unsigned i=0;i<actualCount;++i) {
                ArchiveFileStruct *entry=archive.GetFileStruct(i);
                if(!entry || !entry->isdir) {
                    if(!entry || !ArchiveEraseFixture(dest,entry->filename)) verified=false;
                }
            }
            for(unsigned i=actualCount;i>0;--i) {
                ArchiveFileStruct *entry=archive.GetFileStruct(i-1);
                if(entry && entry->isdir && !ArchiveEraseFixture(dest,entry->filename)) verified=false;
            }
            if(!ArchiveEraseFixture(dest,member) || rmdir(dest)!=0) verified=false;
            // The archive object can keep its input open; unlink only after its destructor below.
        }
        if(fprintf(out,"%s,%d,%u,%llu,%u\n",name,result,actualCount,elapsed,verified)<=0 || fflush(out)!=0) okay=false;
        okay=okay && verified;
        printf("Archive native: %s result=%d count=%u verified=%u\n",name,result,actualCount,verified); fflush(stdout);
    }
    if(okay) {
        char tree[768],file[768],zip[768],dest[768];
        okay=wx_archive_path(tree,sizeof(tree),work,"packtree",true) &&
             wx_archive_path(file,sizeof(file),tree,"empty",true) && wx_archive_directory(file) &&
             wx_archive_path(file,sizeof(file),tree,"sub",true) && wx_archive_directory(file) &&
             wx_archive_path(file,sizeof(file),tree,"sub/payload",true) && ArchiveFixture(file,"original") &&
             wx_archive_path(zip,sizeof(zip),work,"created.zip",true) &&
             wx_archive_path(dest,sizeof(dest),work,"out-pack",true);
        int packed=-1; u64 start=gettime();
        if(okay) { ZipFile writer(zip,ZipFile::CREATE); packed=writer.AddDirectory(tree,"packed",6); }
        unsigned count=0;
        if(okay && packed>0) { ZipFile reader(zip); count=reader.GetItemCount(); packed=reader.ExtractAll(dest); }
        okay=okay && packed>0 && count==4 && wx_archive_path(file,sizeof(file),dest,"packed/sub/payload",true) &&
             ArchiveVerify(file,8,crc32(0,(const Bytef*)"original",8));
        okay=okay && ArchiveEmptyDirectory(dest,"packed/empty");
        if(usbRoot && okay) {
            const char *known[]={"packtree/sub/payload","packtree/sub","packtree/empty","packtree", "out-pack/packed/sub/payload","out-pack/packed/sub","out-pack/packed/empty","out-pack/packed","out-pack","created.zip"};
            for(unsigned i=0;i<sizeof(known)/sizeof(*known);++i) if(!ArchiveEraseFixture(work,known[i])) okay=false;
            rewind(input);
            while(okay && fgets(line,sizeof(line),input)) {
                if(sscanf(line,"%127s",name)!=1 || !ArchiveEraseFixture(work,name)) okay=false;
            }
            if(rmdir(work)!=0) okay=false;
        }
        if(fprintf(out,"pack,%d,%u,%llu,%u\n",packed,count,ticks_to_microsecs(gettime()-start),okay)<=0) okay=false;
    }
    if(ferror(input) || !cases) okay=false;
    if(fclose(input)!=0) okay=false;
    if(fclose(out)!=0) okay=false;
    if(wx_archive_path(report,sizeof(report),root,"archive-complete",true)) ArchiveFixture(report,okay ? "1" : "0");
}
#endif
