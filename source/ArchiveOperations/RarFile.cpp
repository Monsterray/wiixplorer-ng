#include "Diagnostics/MemoryProbes.h"
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
#include <ogcsys.h>
#include <string.h>

#include "Language/gettext.h"
#include "Prompts/ProgressWindow.h"
#include "Prompts/PromptWindows.h"
#include "Tools/tools.h"
#include "RarFile.h"
#include "FileOperations/fileops.h"
#include "RarErrHnd.hpp"
#include "ArchiveSafety.h"
#include <new>
#include <limits>
#include <algorithm>
#include <memory>
#include <limits.h>

ErrorHandler ErrHandler;

RarFile::RarFile(const char *filepath): ListValid(false),StoreBuffer(NULL)
{
    struct stat input;
    if(!filepath || stat(filepath,&input)!=0 || input.st_size<0 || (u64)input.st_size>(u64)LONG_MAX) return;
	RarArc.Open(filepath);
	RarArc.SetExceptions(false);
	ListValid=LoadList();
}

RarFile::~RarFile()
{
	if(!Password.empty()) { volatile char *p=&Password[0]; for(size_t i=0;i<Password.size();++i) p[i]=0; }
	WX_MEMORY_FREE(IO, WX_MEM_RAR_STORE, StoreBuffer, 0x10000); free(StoreBuffer);
	ClearList();
	RarArc.Close();
}

bool RarFile::LoadList()
{
    ClearList(); ErrHandler.Clean();
    if(!RarArc.IsOpened() || !RarArc.IsArchive(false)) return false;
    size_t metadata=0; unsigned headers=0;
    while(RarArc.ReadHeader()>0) {
        if(++headers>WX_ARCHIVE_ITEMS*4 || RarArc.BrokenFileHeader) { ClearList(); return false; }
        if(RarArc.GetHeaderType()==ENDARC_HEAD) break;
        if(RarArc.GetHeaderType()==FILE_HEAD) {
            char name[WX_ARCHIVE_PATH]={0};
            size_t wide=strlenw(RarArc.NewLhd.FileNameW);
            if(wide) {
                // Conversion can use four UTF-8 bytes per source code unit.
                if(wide>=WX_ARCHIVE_PATH) { ClearList(); return false; }
                std::unique_ptr<char[]> utf(new(std::nothrow) char[wide*4+1]);
                if(!utf) { ClearList(); return false; }
                WideToUtf(RarArc.NewLhd.FileNameW,utf.get(),wide*4+1);
                size_t n=strlen(utf.get());
                if(n>=sizeof(name)) { ClearList(); return false; }
                memcpy(name,utf.get(),n+1);
            } else {
                size_t n=strnlen(RarArc.NewLhd.FileName,sizeof(name));
                if(n>=sizeof(name)) { ClearList(); return false; }
                memcpy(name,RarArc.NewLhd.FileName,n+1);
            }
            bool directory=RarArc.IsArcDir();
            unsigned type=RarArc.NewLhd.FileAttr&0170000;
            if(RarArc.NewLhd.HostOS>5 || !wx_archive_member(name) || RarStructure.size()>=WX_ARCHIVE_ITEMS ||
               RarArc.NewLhd.FullUnpSize<0 || RarArc.NewLhd.FullPackSize<0 ||
               (RarArc.NewLhd.HostOS>=3 && type!=(directory ? 0040000u : 0100000u)) ||
               (RarArc.NewLhd.HostOS<3 && (RarArc.NewLhd.FileAttr&0x408)) || (directory && RarArc.NewLhd.FullUnpSize)) { ClearList(); return false; }
            size_t cost=strlen(name)+1+sizeof(ArchiveFileStruct)+sizeof(void*);
            size_t limit=std::min<size_t>(WX_ARCHIVE_METADATA,wx_archive_memory_budget());
            if(metadata>limit || cost>limit-metadata) { ClearList(); return false; }
            ArchiveFileStruct *item=new(std::nothrow) ArchiveFileStruct();
            if(!item) { ClearList(); return false; }
            item->filename=new(std::nothrow) char[strlen(name)+1];
            if(!item->filename) { delete item; ClearList(); return false; }
            strcpy(item->filename,name);
            item->length=(u64)RarArc.NewLhd.FullUnpSize; item->comp_length=(u64)RarArc.NewLhd.FullPackSize;
            item->isdir=directory; item->fileindex=RarStructure.size();
            item->ModTime=RarArc.NewLhd.mtime.GetDos(); item->archiveType=RAR;
            try { RarStructure.push_back(item); } catch(const std::bad_alloc &) { delete [] item->filename; delete item; ClearList(); return false; }
            metadata+=cost;
        }
        int64 position=RarArc.Tell(); RarArc.SeekToNext();
        if(RarArc.Tell()<=position || RarArc.Tell()>RarArc.FileLength() || ErrHandler.GetErrorCode()!=0) { ClearList(); return false; }
    }
    if(ErrHandler.GetErrorCode()!=0 || RarArc.BrokenFileHeader) { ClearList(); return false; }
    return true;
}

void RarFile::ClearList()
{
	for(u32 i = 0; i < RarStructure.size(); i++)
	{
		if(RarStructure.at(i)->filename != NULL)
		{
			delete [] RarStructure.at(i)->filename;
			RarStructure.at(i)->filename = NULL;
		}
		if(RarStructure.at(i) != NULL)
		{
			delete RarStructure.at(i);
			RarStructure.at(i) = NULL;
		}
	}

	RarStructure.clear();
}

ArchiveFileStruct * RarFile::GetFileStruct(int ind)
{
	if(!ListValid || ind >= (int) RarStructure.size() || ind < 0)
		return NULL;

	return RarStructure.at(ind);
}

u32 RarFile::GetItemCount()
{
	return RarStructure.size();
}


bool RarFile::SeekFile(int index)
{
    if(!GetFileStruct(index) || !RarArc.RawSeek(0,SEEK_SET)) return false;
    // ReadHeader expects the signature/main header to have been consumed.
    // Revalidate them after rewinding, rather than treating the signature as
    // an ordinary CRC-protected member header.
    ErrHandler.Clean();
    if(!RarArc.IsArchive(false)) return false;
    unsigned headers=0,member=0;
    while(RarArc.ReadHeader()>0) {
        if(++headers>WX_ARCHIVE_ITEMS*4 || RarArc.BrokenFileHeader) return false;
        if(RarArc.GetHeaderType()==ENDARC_HEAD) break;
        if(RarArc.GetHeaderType()==FILE_HEAD && member++==(unsigned)index) return true;
        int64 before=RarArc.Tell(); RarArc.SeekToNext();
        if(RarArc.Tell()<=before || RarArc.Tell()>RarArc.FileLength()) return false;
    }
    return false;
}

bool RarFile::CheckPassword()
{
	if((RarArc.NewLhd.Flags & LHD_PASSWORD) && Password.length() == 0)
	{
		int choice = WindowPrompt(tr("Password is needed."), tr("Please enter the password."), tr("OK"), tr("Cancel"));
		if(!choice)
			return false;

		char entered[150];
		memset(entered, 0, sizeof(entered));

		bool okay=OnScreenKeyboard(entered,sizeof(entered))!=0;
        if(okay) Password.assign(entered);
        volatile char *wipe=entered; for(size_t i=0;i<sizeof(entered);++i) wipe[i]=0;
        if(!okay) return false;
	}

	return true;
}

class RarFileDataIO: public ComprDataIO
{
public:
    RarFileDataIO(Archive *src,FILE *out,u64 size): failed(false),archive(src),output(out),limit(size),next(0) {}
    int UnpRead(byte *data,size_t count) {
        if(failed || wx_archive_cancelled()) return -1;
        int result=ComprDataIO::UnpRead(data,count);
        if(result<0 || (size_t)result>count || (result==0 && (u64)CurUnpRead<archive->NewLhd.FullPackSize)) { failed=true; return -1; }
        if((u64)CurUnpRead>=next) { ShowProgress(CurUnpRead,archive->NewLhd.FullPackSize); next=(u64)CurUnpRead+256*1024; }
        return result;
    }
    void UnpWrite(byte *data,size_t count) {
        if(failed || wx_archive_cancelled()) { failed=true; return; }
        if(CurUnpWrite<0 || (u64)CurUnpWrite>limit || count>limit-(u64)CurUnpWrite ||
           fwrite(data,1,count,output)!=count) { failed=true; return; }
        // Test mode suppresses the library's unchecked File::Write, while
        // retaining its CRC and byte accounting in the base implementation.
        ComprDataIO::UnpWrite(data,count);
    }
    bool failed;
private:
    Archive *archive; FILE *output; u64 limit,next;
};

void RarFile::UnstoreFile(ComprDataIO &DataIO, int64 DestUnpSize)
{
	if(!StoreBuffer) { StoreBuffer=(byte*)malloc(0x10000); WX_MEMORY_ALLOC(IO, WX_MEM_RAR_STORE, StoreBuffer, 0x10000); }
    if(!StoreBuffer) throw std::bad_alloc();
	while (1)
	{
		uint Code=DataIO.UnpRead(StoreBuffer,0x10000);
		if (Code==0 || (int)Code==-1)
			break;
		Code=Code<DestUnpSize ? Code:(uint)DestUnpSize;
		DataIO.UnpWrite(StoreBuffer,Code);
		if (DestUnpSize>=0)
			DestUnpSize-=Code;
	}
}

int RarFile::InternalExtractFile(int index,const char *root,bool withpath)
{
    ArchiveFileStruct *item=GetFileStruct(index);
    if(!item || !RarArc.IsOpened()) return -1;
    if(wx_archive_cancelled()) return PROGRESS_CANCELED;
    char path[WX_ARCHIVE_PATH];
    if(!wx_archive_path(path,sizeof(path),root,item->filename,withpath)) return -1;
    if(item->isdir) return wx_archive_directory(path) ? 1 : -1;
    // The existing per-member decoder cannot reconstruct earlier solid state
    // or missing volumes. Fail closed instead of publishing incorrect output.
    if(!wx_archive_representable(root,item->length) || RarArc.NewLhd.Flags&(LHD_SOLID|LHD_SPLIT_BEFORE|LHD_SPLIT_AFTER) ||
       item->length>(u64)std::numeric_limits<off_t>::max() ||
       (RarArc.NewLhd.Method!=0x30 && wx_archive_memory_budget()<8u*1024u*1024u)) return -1;
    if(!CheckPassword()) return wx_archive_cancelled() ? PROGRESS_CANCELED : -1;
    ArchiveOutput output;
    if(!output.Begin(root,item->filename,withpath)) return -1;
    ErrHandler.Clean();
    RarFileDataIO data(&RarArc,output.file,item->length);
    data.UnpVolume=false; data.UnpArcSize=RarArc.NewLhd.FullPackSize;
    data.UnpFileCRC=RarArc.OldFormat ? 0 : 0xffffffff; data.PackedCRC=0xffffffff;
    data.SetEncryption((RarArc.NewLhd.Flags&LHD_PASSWORD) ? RarArc.NewLhd.UnpVer : 0,Password.c_str(),
                       (RarArc.NewLhd.Flags&LHD_SALT) ? RarArc.NewLhd.Salt : NULL,false,RarArc.NewLhd.UnpVer>=36);
    data.SetPackedSizeToRead(RarArc.NewLhd.FullPackSize); data.SetFiles(&RarArc,NULL);
    data.SetTestMode(true); data.SetSkipUnpCRC(false); data.EnableShowProgress(false);
    ShowProgress(0,item->length,item->filename);
    try {
    if(RarArc.NewLhd.Method==0x30) UnstoreFile(data,RarArc.NewLhd.FullUnpSize);
    else {
        std::unique_ptr<byte[]> window(new(std::nothrow) byte[MAXWINSIZE]);
        if(!window) return -1;
        std::unique_ptr<Unpack> unpack(new(std::nothrow) Unpack(&data));
        if(!unpack) return -1;
        unpack->Init(window.get());
        if(ErrHandler.GetErrorCode()!=0) return -1;
        unpack->SetDestSize(RarArc.NewLhd.FullUnpSize);
        unpack->DoUnpack(RarArc.NewLhd.UnpVer<=15 ? 15 : RarArc.NewLhd.UnpVer,false);
    }
    } catch(const std::bad_alloc &) { return -1; }
    if(wx_archive_cancelled()) return PROGRESS_CANCELED;
    if(data.failed || data.CurUnpWrite<0 || (u64)data.CurUnpWrite!=item->length ||
       RarArc.ErrorType!=FILE_SUCCESS || ErrHandler.GetErrorCode()!=0 || ErrHandler.GetErrorCount()>0) return -1;
    uint32 expected=RarArc.OldFormat ? RarArc.NewLhd.FileCRC : RarArc.NewLhd.FileCRC^0xffffffff;
    if(UINT32(data.UnpFileCRC)!=UINT32(expected) || !output.Commit()) return -1;
    FinishProgress(item->length); return 1;
}
int RarFile::ExtractFile(int index,const char *root,bool withpath)
{
    int result=SeekFile(index) ? InternalExtractFile(index,root,withpath) : -1;
    WX_MEMORY_FREE(IO, WX_MEM_RAR_STORE, StoreBuffer, 0x10000); free(StoreBuffer); StoreBuffer=NULL; return result;
}
int RarFile::ExtractAll(const char *root)
{
    if(!ListValid || !ArchivePreflight(*this,root)) return -1;
    int result=1;
    for(unsigned i=0;i<GetItemCount() && result>0;++i)
        result=SeekFile(i) ? InternalExtractFile(i,root,true) : -1;
    WX_MEMORY_FREE(IO, WX_MEM_RAR_STORE, StoreBuffer, 0x10000); free(StoreBuffer); StoreBuffer=NULL; return result;
}
