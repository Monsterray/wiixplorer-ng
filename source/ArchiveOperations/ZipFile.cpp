/****************************************************************************
 * Copyright (C) 2009-2011 Dimok
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 ****************************************************************************/
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <malloc.h>
#include <sys/dirent.h>

#include "ZipFile.h"
#include "Prompts/ProgressWindow.h"
#include "FileOperations/fileops.h"
#include "FileOperations/DirList.h"

#include <algorithm>
#include <new>
#include <set>
#include <limits>
#include <memory>
#include <limits.h>
static const u64 ZipLimit=std::min<u64>(UINT32_MAX,LONG_MAX);

ZipFile::ZipFile(const char *filepath,short mode)
    : zFile(NULL),uzFile(NULL),OpenMode(mode),RealArchiveItemCount(0),WriteOutput(NULL),
      IOBuffer(NULL),WriteFailed(false),ListValid(false),WrittenBound(0),WrittenItems(0),MetadataBytes(0)
{
    if(!filepath) return;
    ZipFilePath=filepath;
    if(mode==OPEN || mode==APPEND) { uzFile=unzOpen(filepath); if(uzFile) ListValid=LoadList(); }
}
ZipFile::~ZipFile()
{
    FinishWrite(false); ClearList();
    if(uzFile) unzClose(uzFile);
}

bool ZipFile::SwitchMode(short mode)
{
    if(mode==OPEN) {
        if(zFile || WriteOutput) return false; // Explicitly finish the transaction first.
        if(!uzFile) uzFile=unzOpen(ZipFilePath.c_str());
        return uzFile!=NULL;
    }
    if(mode!=CREATE && mode!=APPEND) return false;
    if(mode==APPEND && !ListValid && !zFile) return false;
    if(zFile) return !WriteFailed;
    if(WriteFailed || ZipFilePath.empty()) return false;
    if(uzFile) { if(unzClose(uzFile)!=UNZ_OK) { uzFile=NULL; return false; } uzFile=NULL; }
    size_t slash=ZipFilePath.rfind('/');
    std::string root=slash==std::string::npos ? "." : ZipFilePath.substr(0,slash+1);
    std::string name=slash==std::string::npos ? ZipFilePath : ZipFilePath.substr(slash+1);
    // A relative current-directory root is trusted, but the member is still validated.
    if(root==".") root="./";
    WriteOutput=new(std::nothrow) ArchiveOutput;
    if(!WriteOutput || !WriteOutput->Begin(root.c_str(),name.c_str(),true)) { FinishWrite(false); return false; }
    WrittenBound=0; WrittenItems=RealArchiveItemCount;
    if(mode==APPEND) {
        struct stat st;
        if(stat(ZipFilePath.c_str(),&st)!=0 || st.st_size<0 || (u64)st.st_size>=ZipLimit) { FinishWrite(false); return false; }
        WrittenBound=st.st_size;
        FILE *source=fopen(ZipFilePath.c_str(),"rb");
        if(!source) { FinishWrite(false); return false; }
        u8 block[16384]; u64 done=0; bool okay=true;
        while(done<WrittenBound) {
            if(wx_archive_cancelled()) { okay=false; break; }
            size_t chunk=(size_t)std::min<u64>(sizeof(block),WrittenBound-done);
            if(fread(block,1,chunk,source)!=chunk || fwrite(block,1,chunk,WriteOutput->file)!=chunk) { okay=false; break; }
            done+=chunk;
        }
        if(fclose(source)!=0) okay=false;
        if(!okay) { FinishWrite(false); return false; }
    }
    FILE *closing=WriteOutput->file; WriteOutput->file=NULL;
    if(fclose(closing)!=0) { FinishWrite(false); return false; }
    zFile=zipOpen(WriteOutput->transfer.staged,mode);
    if(!zFile) { FinishWrite(false); return false; }
    return true;
}

bool ZipFile::FinishWrite(bool success)
{
    bool okay=success && !WriteFailed;
    bool writing=WriteOutput!=NULL;
    if(zFile) { if(zipClose(zFile,NULL)!=ZIP_OK) okay=false; zFile=NULL; }
    if(writing && okay) {
        struct stat st;
        if(stat(WriteOutput->transfer.staged,&st)!=0 || st.st_size<0 || (u64)st.st_size>=ZipLimit ||
           !WriteOutput->Commit()) okay=false;
    }
    delete WriteOutput; WriteOutput=NULL;
    free(IOBuffer); IOBuffer=NULL;
    WriteFailed=false;
    if(writing && okay) { OpenMode=APPEND; return LoadList(); }
    return !writing || okay;
}

void ZipFile::ClearList()
{
    for(unsigned i=0;i<ZipStructure.size();++i) { delete [] ZipStructure[i]->filename; delete ZipStructure[i]; }
    ZipStructure.clear(); MetadataBytes=0; RealArchiveItemCount=0; ListValid=false;
}

bool ZipFile::AppendMetadata(const char *name,u64 size,u64 packed,bool dir,u32 index,u64 time)
{
    if(!wx_archive_member(name) || ZipStructure.size()>=WX_ARCHIVE_ITEMS) return false;
    size_t cost=2*(strlen(name)+1)+sizeof(ArchiveFileStruct)+256; // Includes list/path-index overhead.
    size_t limit=std::min<size_t>(WX_ARCHIVE_METADATA,wx_archive_memory_budget());
    if(MetadataBytes>limit || cost>limit-MetadataBytes) return false;
    ArchiveFileStruct *item=new(std::nothrow) ArchiveFileStruct();
    if(!item) return false;
    item->filename=new(std::nothrow) char[strlen(name)+1];
    if(!item->filename) { delete item; return false; }
    strcpy(item->filename,name);
    item->length=size; item->comp_length=packed; item->isdir=dir;
    item->fileindex=index; item->ModTime=time; item->archiveType=ZIP;
    try { ZipStructure.push_back(item); } catch(const std::bad_alloc &) { delete [] item->filename; delete item; return false; }
    MetadataBytes+=cost;
    return true;
}

bool ZipFile::LoadList()
{
    try { return LoadListInternal(); } catch(const std::bad_alloc &) { ClearList(); return false; }
}
bool ZipFile::LoadListInternal()
{
    ClearList();
    if(!SwitchMode(OPEN)) return false;
    struct stat archiveStat;
    if(stat(ZipFilePath.c_str(),&archiveStat)!=0 || archiveStat.st_size<0 || (u64)archiveStat.st_size>=ZipLimit) return false;
    unz_global_info global;
    if(unzGetGlobalInfo(uzFile,&global)!=UNZ_OK || global.number_entry>WX_ARCHIVE_ITEMS) return false;
    if(!global.number_entry) { ListValid=true; return true; }
    int result=unzGoToFirstFile(uzFile);
    for(unsigned index=0;index<global.number_entry;++index) {
        unz_file_info info;
        char name[WX_ARCHIVE_PATH]={0};
        if(result!=UNZ_OK || unzGetCurrentFileInfo(uzFile,&info,NULL,0,NULL,0,NULL,0)!=UNZ_OK ||
           !info.size_filename || info.size_filename>=sizeof(name) || info.size_file_extra>65535 ||
           info.uncompressed_size>=UINT32_MAX || info.compressed_size>=UINT32_MAX) { ClearList(); return false; }
        std::unique_ptr<unsigned char[]> extra(new(std::nothrow) unsigned char[info.size_file_extra+1]);
        if(!extra) { ClearList(); return false; }
        if(unzGetCurrentFileInfo(uzFile,&info,name,sizeof(name),extra.get(),info.size_file_extra,NULL,0)!=UNZ_OK ||
           strlen(name)!=info.size_filename || !wx_archive_member(name)) { ClearList(); return false; }
        // This pinned minizip exposes classic 32-bit APIs. Reject ZIP64 explicitly.
        for(size_t p=0;p<info.size_file_extra;) {
            if(info.size_file_extra-p<4) { ClearList(); return false; }
            unsigned tag=extra[p]|(extra[p+1]<<8),length=extra[p+2]|(extra[p+3]<<8);
            if(tag==1 || length>info.size_file_extra-p-4) { ClearList(); return false; }
            p+=4+length;
        }
        size_t length=strlen(name);
        unsigned type=(info.external_fa>>16)&0170000;
        bool slash=name[length-1]=='/';
        bool directory=slash || (info.external_fa&0x10) || type==0040000;
        if((type && type!=(directory ? 0040000u : 0100000u)) || (info.external_fa&0x408u) || (directory && info.uncompressed_size)) { ClearList(); return false; }
        if(slash) name[length-1]=0;
        if(!AppendMetadata(name,info.uncompressed_size,info.compressed_size,directory,index,info.dosDate)) { ClearList(); return false; }
        ++RealArchiveItemCount;
        result=unzGoToNextFile(uzFile);
    }
    if(result!=UNZ_END_OF_LIST_OF_FILE || !PathControl()) { ClearList(); return false; }
    ListValid=true; return true;
}

ArchiveFileStruct *ZipFile::GetFileStruct(int index)
{
    return ListValid && index>=0 && (unsigned)index<ZipStructure.size() ? ZipStructure[index] : NULL;
}
bool ZipFile::SeekFile(int index)
{
    ArchiveFileStruct *item=GetFileStruct(index);
    if(!item || item->fileindex==UINT32_MAX || !SwitchMode(OPEN) || unzGoToFirstFile(uzFile)!=UNZ_OK) return false;
    for(unsigned n=0;n<item->fileindex;++n) if(unzGoToNextFile(uzFile)!=UNZ_OK) return false;
    return true;
}
bool ZipFile::PathControl()
{
    std::set<std::string> names;
    unsigned real=ZipStructure.size();
    for(unsigned i=0;i<real;++i) names.insert(ZipStructure[i]->filename);
    for(unsigned i=0;i<real;++i) {
        std::string name=ZipStructure[i]->filename;
        for(size_t p=name.find('/');p!=std::string::npos;p=name.find('/',p+1)) {
            std::string parent=name.substr(0,p);
            if(names.insert(parent).second && !AppendMetadata(parent.c_str(),0,0,true,UINT32_MAX,0)) return false;
        }
    }
    return true;
}

int ZipFile::AddFile(const char *source,const char *member,int level,bool refresh)
{
    try { return AddMember(source,member,level,refresh,NULL); }
    catch(const std::bad_alloc &) { WriteFailed=true; if(refresh) FinishWrite(false); return -1; }
}
int ZipFile::AddMember(const char *source,const char *member,int level,bool refresh,const struct stat *known)
{
    int result=1;
    if(!wx_archive_member(member) || level<Z_DEFAULT_COMPRESSION || level>9) result=-1;
    bool directory=result>0 && member[strlen(member)-1]=='/';
    struct stat st={}; zip_fileinfo info={};
    if(known) st=*known;
    if(result>0 && source && OwnOutput(source)) result=-1;
    if(result>0 && source && ((!known && wx_archive_lstat(source,&st)!=0) || (!directory && !S_ISREG(st.st_mode)) || (directory && !S_ISDIR(st.st_mode)))) result=-1;
    if(result>0 && !directory && (!source || st.st_size<0 || (u64)st.st_size>=ZipLimit)) result=-1;
    if(result>0 && source) {
        struct tm *time=localtime(&st.st_mtime);
        if(!time) result=-1;
        else { info.tmz_date.tm_sec=time->tm_sec; info.tmz_date.tm_min=time->tm_min; info.tmz_date.tm_hour=time->tm_hour;
            info.tmz_date.tm_mday=time->tm_mday; info.tmz_date.tm_mon=time->tm_mon; info.tmz_date.tm_year=time->tm_year; }
    }
    if(result>0 && !SwitchMode(OpenMode==OPEN ? APPEND : OpenMode)) result=-1;
    u64 size=directory ? 0 : (u64)st.st_size;
    // Conservative bound protects classic minizip offset/size fields before writing.
    u64 bound=(u64)compressBound((uLong)size)+128+2*(member ? strlen(member) : 0);
    if(result>0 && (WrittenItems>=WX_ARCHIVE_ITEMS || bound>=ZipLimit-WrittenBound)) result=-1;
    FILE *input=NULL;
    if(result>0 && !directory) {
        input=fopen(source,"rb");
        if(!IOBuffer) IOBuffer=(u8*)malloc(1024*70);
        struct stat openedStat;
        if(!input || !IOBuffer || fstat(fileno(input),&openedStat)!=0 || !S_ISREG(openedStat.st_mode) || openedStat.st_size!=st.st_size) result=-1;
    }
    bool opened=false;
    if(result>0) {
        opened=zipOpenNewFileInZip(zFile,member,&info,NULL,0,NULL,0,NULL,Z_DEFLATED,level)==ZIP_OK;
        if(!opened) result=-1;
    }
    u64 done=0,next=0;
    while(result>0 && done<size) {
        if(wx_archive_cancelled()) { result=PROGRESS_CANCELED; break; }
        if(done>=next) { ShowProgress(done,size,member); next=done+256*1024; }
        size_t chunk=(size_t)std::min<u64>(1024*70,size-done);
        size_t got=fread(IOBuffer,1,chunk,input);
        if(got!=chunk || ferror(input) || zipWriteInFileInZip(zFile,IOBuffer,(unsigned)got)!=ZIP_OK) { result=-1; break; }
        done+=got;
    }
    if(input && result>0 && (fgetc(input)!=EOF || ferror(input))) result=-1;
    if(input && fclose(input)!=0) result=-1;
    if(opened && zipCloseFileInZip(zFile)!=ZIP_OK) result=-1;
    if(wx_archive_cancelled()) result=PROGRESS_CANCELED;
    if(result>0) { WrittenBound+=bound; ++WrittenItems; FinishProgress(size); }
    else WriteFailed=true;
    if(refresh && !FinishWrite(result>0)) { if(result>0) result=-1; }
    return result;
}

bool ZipFile::OwnOutput(const char *path) const
{
    if(!strcasecmp(path,ZipFilePath.c_str())) return true;
    if(!WriteOutput) return false;
    const char *directory=WriteOutput->transfer.directory;
    size_t length=strlen(directory);
    return !strncasecmp(path,directory,length) && (!path[length] || path[length]=='/');
}

int ZipFile::WalkDirectory(const char *source,const char *member,int level,unsigned depth,unsigned &count,const struct stat *known)
{
    if(depth>=WX_ARCHIVE_DEPTH || ++count>WX_ARCHIVE_ITEMS || !wx_archive_member(member)) return -1;
    struct stat st;
    if(known) st=*known;
    if((!known && wx_archive_lstat(source,&st)!=0) || !S_ISDIR(st.st_mode)) return -1;
    std::string directory=member;
    if(directory.back()!='/') directory+='/';
    int result=AddMember(source,directory.c_str(),level,false,&st);
    if(result<0) return result;
    DIR *dir=opendir(source);
    if(!dir) return -1;
    std::unique_ptr<DIR,int(*)(DIR*)> owner(dir,closedir);
    while(result>0) {
        if(wx_archive_cancelled()) { result=PROGRESS_CANCELED; break; }
        errno=0; struct dirent *entry=readdir(dir);
        if(!entry) { if(errno) result=-1; break; }
        if(!strcmp(entry->d_name,".") || !strcmp(entry->d_name,"..")) continue;
        std::string path=std::string(source)+"/"+entry->d_name,name=directory+entry->d_name;
        if(OwnOutput(path.c_str())) continue; // Never recursively compress our own output/staging.
        if(path.size()>=WX_ARCHIVE_PATH || !wx_archive_member(name.c_str()) || wx_archive_lstat(path.c_str(),&st)!=0) { result=-1; break; }
        if(S_ISDIR(st.st_mode)) result=WalkDirectory(path.c_str(),name.c_str(),level,depth+1,count,&st);
        else if(S_ISREG(st.st_mode) && ++count<=WX_ARCHIVE_ITEMS) result=AddMember(path.c_str(),name.c_str(),level,false,&st);
        else result=-1;
    }
    if(closedir(owner.release())!=0) result=-1;
    return result;
}
int ZipFile::AddDirectory(const char *source,const char *member,int level,bool refresh)
{
    unsigned count=0;
    int result=-1;
    try { if(source && member) result=WalkDirectory(source,member,level,0,count); }
    catch(const std::bad_alloc &) { result=-1; }
    if(result<0) WriteFailed=true;
    if(refresh && !FinishWrite(result>0) && result>0) result=-1;
    return result;
}

int ZipFile::ExtractMember(int index,const char *root,bool withpath,void *buffer,size_t capacity)
{
    ArchiveFileStruct *item=GetFileStruct(index);
    char path[WX_ARCHIVE_PATH];
    if(wx_archive_cancelled()) return PROGRESS_CANCELED;
    if(!item || !wx_archive_path(path,sizeof(path),root,item->filename,withpath)) return -1;
    if(item->isdir) return wx_archive_directory(path) ? 1 : -1;
    if(!wx_archive_representable(root,item->length) || !buffer || !SeekFile(index) || unzOpenCurrentFile(uzFile)!=UNZ_OK) return -1;
    ArchiveOutput output;
    int result=output.Begin(root,item->filename,withpath) ? 1 : -1;
    u64 done=0,next=0;
    while(result>0 && done<item->length) {
        if(wx_archive_cancelled()) { result=PROGRESS_CANCELED; break; }
        if(done>=next) { ShowProgress(done,item->length,item->filename); next=done+256*1024; }
        unsigned chunk=(unsigned)std::min<u64>(capacity,item->length-done);
        int got=unzReadCurrentFile(uzFile,buffer,chunk);
        if(got<=0 || (unsigned)got>chunk || fwrite(buffer,1,(size_t)got,output.file)!=(size_t)got) { result=-1; break; }
        done+=(unsigned)got;
    }
    // Verify EOF even for empty members, and check the backend's CRC on close.
    if(result>0 && unzReadCurrentFile(uzFile,buffer,1)!=0) result=-1;
    if(unzCloseCurrentFile(uzFile)!=UNZ_OK) result=-1;
    if(wx_archive_cancelled()) result=PROGRESS_CANCELED;
    if(result>0 && !output.Commit()) result=-1;
    if(result>0) FinishProgress(item->length);
    return result;
}
int ZipFile::ExtractFile(int index,const char *root,bool withpath)
{
    void *buffer=malloc(1024*50);
    if(!buffer) return -1;
    int result=ExtractMember(index,root,withpath,buffer,1024*50);
    free(buffer); return result;
}
int ZipFile::ExtractAll(const char *root)
{
    if(!ListValid || !SwitchMode(OPEN) || !ArchivePreflight(*this,root)) return -1;
    void *buffer=malloc(1024*70);
    if(!buffer) return -1;
    int result=1;
    for(unsigned i=0;i<ZipStructure.size() && result>0;++i) result=ExtractMember(i,root,true,buffer,1024*70);
    free(buffer); return result;
}
