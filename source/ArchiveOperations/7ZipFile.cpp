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
#include <stdio.h>
#include <string.h>

#include "Prompts/PromptWindows.h"
#include "Prompts/ProgressWindow.h"
#include "FileOperations/fileops.h"
#include "TextOperations/wstring.hpp"
#include "7ZipFile.h"

// 7zip error list
static const char * szerrormsg[10] = {
   tr("File is corrupt."), // 7z: Data error
   tr("Not enough memory."), // 7z: Out of memory
   tr("File is corrupt (CRC mismatch)."), // 7z: CRC Error
   tr("File uses unsupported compression settings."), // 7z: Not implemented
   tr("File is corrupt."), // 7z: Fail
   tr("Failed to read file data."), // 7z: Data read failure
   tr("File is corrupt."), // 7z: Archive error
   tr("File uses too high of compression settings (dictionary size is too large)."), // 7z: Dictionary too large
   tr("Can't open file."),
   tr("Process canceled."),
};

#include <algorithm>
#include <limits>
#include <limits.h>

union SzAllocationHeader { size_t size; long double alignment; };
void *SzFile::BudgetAlloc(void *p,size_t size)
{
    BudgetAllocator *allocator=(BudgetAllocator*)p;
    if(!size || size>SIZE_MAX-sizeof(SzAllocationHeader) || *allocator->used>allocator->limit ||
       size+sizeof(SzAllocationHeader)>allocator->limit-*allocator->used) {
        WX_MEMORY_ALLOC(IO, WX_MEM_SEVEN_SDK, NULL, size);
        return NULL;
    }
    SzAllocationHeader *header=(SzAllocationHeader*)malloc(size+sizeof(*header));
    WX_MEMORY_ALLOC(IO, WX_MEM_SEVEN_SDK, header, size+sizeof(*header));
    if(!header) return NULL;
    header->size=size+sizeof(*header); *allocator->used+=header->size;
    return header+1;
}
void SzFile::BudgetFree(void *p,void *address)
{
    if(!address) return;
    SzAllocationHeader *header=(SzAllocationHeader*)address-1;
    BudgetAllocator *allocator=(BudgetAllocator*)p;
    *allocator->used-=header->size;
    WX_MEMORY_FREE(IO, WX_MEM_SEVEN_SDK, header, header->size);
    free(header);
}
SzFile::SzFile(const char *path): SzResult(SZ_ERROR_FAIL),Allocated(0),Decoded(NULL),DecodedSize(0),SzBlockIndex(0xffffffff)
{
    memset(&CurArcFile,0,sizeof(CurArcFile));
    File_Construct(&archiveStream.file); SzArEx_Init(&SzArchiveDb);
    MainAlloc.api.Alloc=TempAlloc.api.Alloc=BudgetAlloc;
    MainAlloc.api.Free=TempAlloc.api.Free=BudgetFree;
    MainAlloc.used=TempAlloc.used=&Allocated;
    MainAlloc.limit=TempAlloc.limit=std::min<size_t>(WX_ARCHIVE_METADATA,wx_archive_memory_budget());
    struct stat input;
    if(!path || stat(path,&input)!=0 || input.st_size<0 || (u64)input.st_size>(u64)LONG_MAX || InFile_Open(&archiveStream.file,path)) { SzResult=9; return; }
    FileInStream_CreateVTable(&archiveStream);
    LookToRead_CreateVTable(&lookStream,False);
    lookStream.realStream=&archiveStream.s; LookToRead_Init(&lookStream);
    CrcGenerateTable();
    SzResult=SzArEx_Open(&SzArchiveDb,&lookStream.s,&MainAlloc.api,&TempAlloc.api);
    if(SzResult==SZ_OK && SzArchiveDb.db.NumFiles>WX_ARCHIVE_ITEMS) SzResult=SZ_ERROR_MEM;
    if(SzResult==SZ_OK) {
        for(unsigned i=0;i<SzArchiveDb.db.NumFiles;++i) {
            if(!GetFileStruct(i)) { SzResult=SZ_ERROR_DATA; break; }
        }
    }
    if(SzResult!=SZ_OK) DisplayError(SzResult);
}
void SzFile::FreeDecoded()
{
    IAlloc_Free(&MainAlloc.api,Decoded); Decoded=NULL; DecodedSize=0; SzBlockIndex=0xffffffff;
}
SzFile::~SzFile()
{
    FreeDecoded(); SzArEx_Free(&SzArchiveDb,&MainAlloc.api);
    File_Close(&archiveStream.file); free(CurArcFile.filename);
}
char *SzFile::GetUtf8Filename(int index)
{
    if(SzResult!=SZ_OK || index<0 || (unsigned)index>=SzArchiveDb.db.NumFiles) return NULL;
    size_t length=SzArEx_GetFileNameUtf16(&SzArchiveDb,index,NULL);
    if(!length || length>WX_ARCHIVE_PATH) return NULL;
    UInt16 name[WX_ARCHIVE_PATH];
    if(SzArEx_GetFileNameUtf16(&SzArchiveDb,index,name)!=length || name[length-1]!=0) return NULL;
    wString wide;
    for(size_t i=0;i+1<length;++i) { if(!name[i]) return NULL; wide.push_back(name[i]); }
    std::string utf=wide.toUTF8();
    if(!wx_archive_member(utf.c_str())) return NULL;
    return strdup(utf.c_str());
}

bool SzFile::Is7ZipFile (const char *buffer)
{
	// 7z signature
	int i;
	for(i = 0; i < 6; i++)
		if(buffer[i] != k7zSignature[i])
			return false;

	return true; // 7z archive found
}

ArchiveFileStruct *SzFile::GetFileStruct(int index)
{
    if(SzResult!=SZ_OK || index<0 || (unsigned)index>=SzArchiveDb.db.NumFiles) return NULL;
    const CSzFileItem *item=SzArchiveDb.db.Files+index;
    unsigned type=item->Attrib>>16 & 0170000;
    if((item->IsDir && item->Size) || item->IsAnti || (item->AttribDefined && ((item->Attrib&0x408) ||
       (type && type!=(item->IsDir ? 0040000u : 0100000u))))) return NULL;
    char *name=GetUtf8Filename(index);
    if(!name) return NULL;
    free(CurArcFile.filename); CurArcFile.filename=name;
    CurArcFile.length=item->Size; CurArcFile.comp_length=0;
    CurArcFile.isdir=item->IsDir; CurArcFile.fileindex=index;
    CurArcFile.ModTime=item->MTimeDefined ? (u64)item->MTime.Low | ((u64)item->MTime.High<<32) : 0;
    CurArcFile.archiveType=SZIP;
    return &CurArcFile;
}

void SzFile::DisplayError(SRes res)
{
	const char *cpErrString = (res > 0 && res < 10) ? szerrormsg[(res - 1)] : "";
	ThrowMsg(tr("7z decompression failed:"), "%s %i: %s", tr("Error"), res, cpErrString);
}

u32 SzFile::GetItemCount()
{
	if(SzResult != SZ_OK)
		return 0;

	return SzArchiveDb.db.NumFiles;
}

int SzFile::ExtractMember(int index,const char *root,bool withpath)
{
    if(!GetFileStruct(index)) return -1;
    if(wx_archive_cancelled()) return PROGRESS_CANCELED;
    char path[WX_ARCHIVE_PATH];
    if(!wx_archive_path(path,sizeof(path),root,CurArcFile.filename,withpath)) return -1;
    if(CurArcFile.isdir) return wx_archive_directory(path) ? 1 : -1;
    if(!wx_archive_representable(root,CurArcFile.length) || CurArcFile.length>SIZE_MAX) return -1; // SDK returns an in-memory size_t slice.
    size_t offset=0,size=0;
    ShowProgress(0,CurArcFile.length,CurArcFile.filename);
    SRes result=SzArEx_Extract(&SzArchiveDb,&lookStream.s,index,&SzBlockIndex,&Decoded,&DecodedSize,
                              &offset,&size,&MainAlloc.api,&TempAlloc.api);
    if(wx_archive_cancelled()) return PROGRESS_CANCELED;
    if(result!=SZ_OK || size!=CurArcFile.length || offset>DecodedSize || size>DecodedSize-offset || (size && !Decoded)) {
        if(result!=SZ_OK) DisplayError(result);
        return -1;
    }
    ArchiveOutput output;
    if(!output.Begin(root,CurArcFile.filename,withpath)) return -1;
    size_t done=0,next=0;
    while(done<size) {
        if(wx_archive_cancelled()) return PROGRESS_CANCELED;
        if(done>=next) { ShowProgress(done,CurArcFile.length,CurArcFile.filename); next=done+256*1024; }
        size_t chunk=std::min<size_t>(51200,size-done);
        if(fwrite(Decoded+offset+done,1,chunk,output.file)!=chunk) return -1;
        done+=chunk;
    }
    if(wx_archive_cancelled()) return PROGRESS_CANCELED;
    if(!output.Commit()) return -1;
    FinishProgress(CurArcFile.length); return 1;
}
int SzFile::ExtractFile(int index,const char *root,bool withpath)
{
    WX_MEMORY_OPERATION("seven_begin", "seven_end");
    MainAlloc.limit=TempAlloc.limit=std::min<size_t>(16u*1024u*1024u,Allocated+wx_archive_memory_budget());
    int result=ExtractMember(index,root,withpath); FreeDecoded(); return result;
}
int SzFile::ExtractAll(const char *root)
{
    WX_MEMORY_OPERATION("seven_all_begin", "seven_all_end");
    if(SzResult!=SZ_OK || !ArchivePreflight(*this,root)) return -1;
    MainAlloc.limit=TempAlloc.limit=std::min<size_t>(16u*1024u*1024u,Allocated+wx_archive_memory_budget());
    int result=1;
    for(unsigned i=0;i<GetItemCount() && result>0;++i) result=ExtractMember(i,root,true);
    FreeDecoded(); return result;
}
