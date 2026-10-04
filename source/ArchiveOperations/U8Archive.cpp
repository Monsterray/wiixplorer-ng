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

#include "Prompts/PromptWindows.h"
#include "FileOperations/fileops.h"
#include "Tools/uncompress.h"
#include "U8Archive.h"
#include "ArchiveSafety.h"
#include <new>
#include <algorithm>

U8Archive::U8Archive(const char *filepath)
	: WiiArchive(filepath)
{
	try { ParseFile(); } catch(const std::bad_alloc &) { CloseFile(); }
}

U8Archive::U8Archive(const u8 * Buffer, u32 Size)
	: WiiArchive(Buffer, Size)
{
	try { ParseFile(); } catch(const std::bad_alloc &) { CloseFile(); }
}

U8Archive::~U8Archive()
{
	CloseFile();
}

bool U8Archive::ParseFile()
{
    ClearList();
    u8 header[sizeof(IMETHeader)]={0};
    if(FileSize<4 || ReadFile(header,(size_t)std::min<u64>(FileSize,sizeof(header)),0)==0) return false;
    bool okay=false;
    if(FileSize>=sizeof(IMETHeader) && !memcmp(header+64,"IMET",4)) {
        if(AddListEntrie("header.imet",sizeof(IMETHeader),sizeof(IMETHeader),false,0,0,U8Arch)) {
            BufferOffset.push_back(0);
            okay=ParseU8Header(sizeof(IMETHeader));
        }
    } else if(!memcmp(header,"IMD5",4)) {
        u64 declared=wx_archive_be32(header+4);
        if(FileSize<36 || declared>FileSize-32) { CloseFile(); return false; }
        if(!memcmp(header+32,"LZ77",4)) {
            u64 input=FileSize-32;
            u32 output=header[37]|((u32)header[38]<<8)|((u32)header[39]<<16);
            if(FileSize<40 || input>SIZE_MAX || input+output>wx_archive_memory_budget()) { CloseFile(); return false; }
            u8 *compressed=(u8*)malloc((size_t)input);
            u32 decodedSize=0;
            u8 *decoded=NULL;
            if(compressed && ReadFile(compressed,(size_t)input,32)==input)
                decoded=uncompressLZ77(compressed,(u32)input,&decodedSize);
            free(compressed);
            CloseFile();
            if(!decoded) return false;
            FileBuffer=decoded; FileSize=decodedSize; FromMem=true;
            okay=ParseU8Header(0);
        } else okay=ParseU8Header(32);
    } else if(wx_archive_be32(header)==0x55aa382d) okay=ParseU8Header(0);
    if(!okay) CloseFile();
    return okay;
}

bool U8Archive::ParseU8Header(u32 base)
{
    u8 header[32],root[12];
    if(ReadFile(header,sizeof(header),base)!=sizeof(header) || wx_archive_be32(header)!=0x55aa382d) return false;
    u64 fst=(u64)base+wx_archive_be32(header+4);
    u64 end=fst+wx_archive_be32(header+8),data=(u64)base+wx_archive_be32(header+12);
    if(fst<(u64)base+32 || end>FileSize || data<end || data>FileSize || ReadFile(root,12,fst)!=12) return false;
    u32 count=wx_archive_be32(root+8);
    if(root[0]!=1 || wx_archive_be32(root+4)!=0 || !count || count>WX_ARCHIVE_ITEMS ||
       (u64)count*12>end-fst) return false;
    u64 strings=fst+(u64)count*12;
    // Bounded iterative directory stack: end indices and prefix lengths.
    u32 ends[WX_ARCHIVE_DEPTH+1]={count},parents[WX_ARCHIVE_DEPTH+1]={0};
    size_t lengths[WX_ARCHIVE_DEPTH+1]={0};
    unsigned depth=0;
    string prefix;
    for(u32 i=1;i<count;++i) {
        while(depth && i==ends[depth]) { prefix.resize(lengths[depth]); --depth; }
        if(i>=ends[depth]) return false;
        u8 entry[12];
        if(ReadFile(entry,12,fst+(u64)i*12)!=12 || entry[0]>1) return false;
        u32 nameOffset=wx_archive_be32(entry)&0xffffff;
        u64 position=strings+nameOffset;
        if(position>=end) return false;
        string name;
        for(;position<end && name.size()<255;++position) {
            char c;
            if(ReadFile(&c,1,position)!=1) return false;
            if(!c) break;
            name+=c;
        }
        char zero=1;
        if(position>=end || ReadFile(&zero,1,position)!=1 || zero || !wx_archive_member(name.c_str()) || name.find('/')!=string::npos) return false;
        string path=prefix+name;
        bool directory=entry[0]==1;
        u32 offset=wx_archive_be32(entry+4),length=wx_archive_be32(entry+8);
        if(directory) {
            if(offset!=parents[depth] || length<=i || length>ends[depth] || depth+1>=WX_ARCHIVE_DEPTH) return false;
        } else if((u64)base+offset<data || (u64)base+offset>FileSize || length>FileSize-((u64)base+offset)) return false;
        if(!AddListEntrie(path.c_str(),directory ? 0 : length,directory ? 0 : length,directory,GetItemCount(),0,U8Arch)) return false;
        BufferOffset.push_back(directory ? 0 : (u64)base+offset);
        if(directory) { ++depth; ends[depth]=length; parents[depth]=i; lengths[depth]=prefix.size(); prefix=path+"/"; }
    }
    return true;
}
