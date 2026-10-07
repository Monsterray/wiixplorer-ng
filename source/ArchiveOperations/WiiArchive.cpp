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
#include <stdlib.h>
#include <string.h>
#include <malloc.h>
#include "Diagnostics/MemoryProbes.h"

#include "Prompts/PromptWindows.h"
#include "Prompts/ProgressWindow.h"
#include "FileOperations/fileops.h"
#include "WiiArchive.h"
#include "ArchiveSafety.h"
#include <new>
#include <algorithm>
#include <limits>

WiiArchive::WiiArchive(const char *filepath)
{
	File = NULL;
	FileBuffer = NULL;
	FileSize = 0;
	MetadataBytes = 0;
	FromMem = false;

	LoadFile(filepath);
}

WiiArchive::WiiArchive(const u8 * Buffer, u32 Size)
{
	File = NULL;
	FileBuffer = NULL;
	FileSize = 0;
	MetadataBytes = 0;
	FromMem = true;

	if(Buffer)
	{
		LoadFile(Buffer, Size);
	}
}

WiiArchive::~WiiArchive()
{
	CloseFile();
}

void WiiArchive::CloseFile()
{
	ClearList();

	if(FileBuffer) {
        WX_MEMORY_FREE(IO,WX_MEM_ARCHIVE_BUFFER,FileBuffer,FileSize);
        free(FileBuffer);
    }

	if(File)
		fclose(File);

	File = NULL;
	FileBuffer = NULL;
	FileSize = 0;
	MetadataBytes = 0;
	FromMem = false;
}

bool WiiArchive::LoadFile(const char * filepath)
{
	if(!filepath)
		return false;

	CloseFile();

	File = fopen(filepath, "rb");
	if(!File)
		return false;

    struct stat st;
    if(fstat(fileno(File),&st)!=0 || st.st_size<0 ||
       (u64)st.st_size>(u64)std::numeric_limits<off_t>::max()) { CloseFile(); return false; }
    FileSize=(u64)st.st_size;
    FromMem=false;

	return true;
}

bool WiiArchive::LoadFile(const u8 * Buffer, u32 Size)
{
	if(!Buffer || !Size || Size>wx_archive_memory_budget())
		return false;

	CloseFile();

	FileBuffer = (u8 *) malloc(Size);
    WX_MEMORY_ALLOC(IO,WX_MEM_ARCHIVE_BUFFER,FileBuffer,Size);
	if(!FileBuffer)
		return false;

	FileSize = Size;

	FromMem = true;

	memcpy(FileBuffer, Buffer, FileSize);

	return true;
}

ArchiveFileStruct * WiiArchive::GetFileStruct(int ind)
{
	if(ind >= (int) PathStructure.size() || ind < 0)
		return NULL;

	return PathStructure.at(ind);
}

bool WiiArchive::AddListEntrie(const char *filename,u64 length,u64 comp_length,bool isdir,u32 index,u64 modtime,u8 Type)
{
    if(!wx_archive_member(filename) || PathStructure.size()>=WX_ARCHIVE_ITEMS) return false;
    size_t cost=strlen(filename)+1+sizeof(ArchiveFileStruct)+sizeof(void*)+sizeof(u64);
    if(MetadataBytes>wx_archive_memory_budget() || cost>std::min<size_t>(WX_ARCHIVE_METADATA,wx_archive_memory_budget())-MetadataBytes) return false;
    ArchiveFileStruct *item=new(std::nothrow) ArchiveFileStruct();
    if(!item) return false;
    item->filename=new(std::nothrow) char[strlen(filename)+1];
    if(!item->filename) { delete item; return false; }
    strcpy(item->filename,filename);
    item->length=length; item->comp_length=comp_length; item->isdir=isdir;
    item->fileindex=index; item->ModTime=modtime; item->archiveType=Type;
    try { PathStructure.push_back(item); } catch(const std::bad_alloc &) { delete [] item->filename; delete item; return false; }
    MetadataBytes+=cost;
    return true;
}

void WiiArchive::ClearList()
{
	for(u32 i = 0; i < PathStructure.size(); i++)
	{
		if(PathStructure.at(i)->filename != NULL)
		{
			delete [] PathStructure.at(i)->filename;
			PathStructure.at(i)->filename = NULL;
		}
		if(PathStructure.at(i) != NULL)
		{
			delete PathStructure.at(i);
			PathStructure.at(i) = NULL;
		}
	}

	PathStructure.clear();
	BufferOffset.clear();
	MetadataBytes=0;
}

size_t WiiArchive::ReadFile(void *buffer,size_t size,u64 offset)
{
    if(!buffer || offset>FileSize || size>FileSize-offset) return 0;
    if(FromMem) {
        if(!FileBuffer || offset>SIZE_MAX || size>SIZE_MAX-(size_t)offset) return 0;
        memcpy(buffer,FileBuffer+(size_t)offset,size); return size;
    }
    if(!File || offset>(u64)std::numeric_limits<off_t>::max() ||
       fseeko(File,(off_t)offset,SEEK_SET)!=0) return 0;
    size_t got=fread(buffer,1,size,File);
    return got==size && !ferror(File) ? got : 0;
}

int WiiArchive::ExtractMember(int ind,const char *dest,bool withpath,u8 *buffer,size_t capacity)
{
    ArchiveFileStruct *item=GetFileStruct(ind);
    if(wx_archive_cancelled()) return PROGRESS_CANCELED;
    if(!item || item->fileindex>=BufferOffset.size()) return -1;
    char path[WX_ARCHIVE_PATH];
    if(!wx_archive_path(path,sizeof(path),dest,item->filename,withpath)) return -1;
    if(item->isdir) return wx_archive_directory(path) ? 1 : -1;
    u64 offset=BufferOffset[item->fileindex];
    if(!wx_archive_representable(dest,item->length) || offset>FileSize || item->length>FileSize-offset) return -1;
    ArchiveOutput output;
    if(!output.Begin(dest,item->filename,withpath)) return -1;
    if(!buffer) return -1;
    u64 done=0,next=0;
    int result=1;
    while(done<item->length) {
        if(wx_archive_cancelled()) { result=PROGRESS_CANCELED; break; }
        if(done>=next) { ShowProgress(done,item->length,item->filename); next=done+256*1024; }
        size_t chunk=(size_t)std::min<u64>(capacity,item->length-done);
        if(ReadFile(buffer,chunk,offset+done)!=chunk || fwrite(buffer,1,chunk,output.file)!=chunk) { result=-1; break; }
        done+=chunk;
    }
    if(wx_archive_cancelled()) result=PROGRESS_CANCELED;
    if(result>0 && !output.Commit()) result=-1;
    if(result>0) FinishProgress(item->length);
    return result;
}

int WiiArchive::ExtractFile(int index,const char *dest,bool withpath)
{
    u8 *buffer=(u8*)malloc(1024*50);
    WX_MEMORY_BUFFER(IO,WX_MEM_ARCHIVE_SCRATCH,buffer,1024*50);
    if(!buffer) return -1;
    int result=ExtractMember(index,dest,withpath,buffer,1024*50);
    free(buffer); return result;
}
int WiiArchive::ExtractAll(const char *dest)
{
    if((!FileBuffer && !File) || !ArchivePreflight(*this,dest)) return -1;
    u8 *buffer=(u8*)malloc(1024*50);
    WX_MEMORY_BUFFER(IO,WX_MEM_ARCHIVE_SCRATCH,buffer,1024*50);
    if(!buffer) return -1;
    int result=1;
    for(unsigned i=0;i<PathStructure.size() && result>0;++i)
        result=ExtractMember(i,dest,true,buffer,1024*50);
    free(buffer); return result;
}
