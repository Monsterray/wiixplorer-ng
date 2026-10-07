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
#include "FileOperations/fileops.h"
#include "Tools/uncompress.h"
#include "RarcFile.h"
#include "ArchiveSafety.h"
#include <new>

RarcFile::RarcFile(const char *filepath)
	: WiiArchive(filepath)
{
	try { ParseFile(); } catch(const std::bad_alloc &) { CloseFile(); }
}

RarcFile::RarcFile(const u8 * Buffer, u32 Size)
	: WiiArchive(Buffer, Size)
{
	try { ParseFile(); } catch(const std::bad_alloc &) { CloseFile(); }
}

RarcFile::~RarcFile()
{
	CloseFile();
}

bool RarcFile::ParseFile()
{
    ClearList();
    u8 header[16];
    if(ReadFile(header,16,0)!=16) return false;
    if(!memcmp(header,"Yaz0",4)) {
        u32 size=wx_archive_be32(header+4);
        if(!size || FileSize>UINT32_MAX || FileSize+size>wx_archive_memory_budget()) { CloseFile(); return false; }
        u32 input=(u32)FileSize;
        const bool scratch=!FromMem;
        u8 *compressed=scratch ? (u8*)malloc(input) : FileBuffer;
        u8 *decoded=(u8*)malloc(size);
        if(scratch) WX_MEMORY_ALLOC(IO,WX_MEM_ARCHIVE_SCRATCH,compressed,input);
        WX_MEMORY_ALLOC(IO,WX_MEM_ARCHIVE_BUFFER,decoded,size);
        bool okay=compressed && decoded && (!scratch || ReadFile(compressed,input,0)==input) && uncompressYaz0(compressed,input,decoded,size);
        if(scratch) {
            WX_MEMORY_FREE(IO,WX_MEM_ARCHIVE_SCRATCH,compressed,input);
            free(compressed);
        }
        CloseFile();
        if(!okay) { WX_MEMORY_FREE(IO,WX_MEM_ARCHIVE_BUFFER,decoded,size);free(decoded);return false; }
        FileBuffer=decoded; FileSize=size; FromMem=true;
    }
    if(!ParseRarcHeader()) { CloseFile(); return false; }
    return true;
}

bool RarcFile::ParseRarcHeader()
{
    u8 h[64];
    if(ReadFile(h,64,0)!=64 || memcmp(h,"RARC",4)) return false;
    u64 declared=wx_archive_be32(h+4);
    NodeCount=wx_archive_be32(h+32); EntryCount=wx_archive_be32(h+40);
    NodesOffset=32ull+wx_archive_be32(h+36);
    EntriesOffset=32ull+wx_archive_be32(h+44);
    StringsOffset=32ull+wx_archive_be32(h+52);
    StringsEnd=StringsOffset+wx_archive_be32(h+48);
    DataStart=32ull+wx_archive_be32(h+12);
    if(declared<64 || declared>FileSize || !NodeCount || NodeCount>WX_ARCHIVE_ITEMS || EntryCount>WX_ARCHIVE_ITEMS ||
       NodesOffset<64 || NodesOffset+(u64)NodeCount*16>EntriesOffset || EntriesOffset<64 ||
       EntriesOffset+(u64)EntryCount*20>StringsOffset || StringsOffset<64 || StringsEnd>declared ||
       DataStart<StringsEnd || DataStart>declared) return false;
    FileSize=declared;
    Seen.assign(NodeCount,0); VisitedEntries=0;
    return ParseNode(0,"",0);
}

bool RarcFile::GetFilename(u64 offset,string &name)
{
    name.clear();
    if(offset<StringsOffset || offset>=StringsEnd) return false;
    while(offset<StringsEnd && name.size()<=255) {
        char c;
        if(ReadFile(&c,1,offset++)!=1) return false;
        if(!c) return !name.empty();
        name+=c;
    }
    return false;
}

bool RarcFile::ParseNode(u32 index,const string &parent,unsigned depth)
{
    if(index>=NodeCount || depth>=WX_ARCHIVE_DEPTH || Seen[index]) return false;
    Seen[index]=1; // Reject cycles and repeated node aliases, including completed nodes.
    u8 node[16];
    if(ReadFile(node,16,NodesOffset+(u64)index*16)!=16) return false;
    u32 first=wx_archive_be32(node+12),count=wx_archive_be16(node+10);
    if(first>EntryCount || count>EntryCount-first || count>WX_ARCHIVE_ITEMS-VisitedEntries) return false;
    VisitedEntries+=count;
    string name;
    if(!GetFilename(StringsOffset+wx_archive_be32(node+4),name) || !wx_archive_member(name.c_str()) || name.find('/')!=string::npos) return false;
    string path=parent.empty() ? name : parent+"/"+name;
    if(!AddListEntrie(path.c_str(),0,0,true,GetItemCount(),0,ArcArch)) return false;
    BufferOffset.push_back(0);
    for(u32 i=0;i<count;++i) {
        u8 entry[20];
        if(ReadFile(entry,20,EntriesOffset+(u64)(first+i)*20)!=20 ||
           !GetFilename(StringsOffset+wx_archive_be16(entry+6),name)) return false;
        u32 offset=wx_archive_be32(entry+8),size=wx_archive_be32(entry+12);
        if(wx_archive_be16(entry)==0xffff) {
            if(offset>=NodeCount) return false;
            if(name=="." || name=="..") continue; // Structural RARC parent/self entries.
            if(!wx_archive_member(name.c_str()) || name.find('/')!=string::npos || !ParseNode(offset,path,depth+1)) return false;
        } else {
            if(!wx_archive_member(name.c_str()) || name.find('/')!=string::npos ||
               DataStart+offset>FileSize || size>FileSize-(DataStart+offset)) return false;
            string child=path+"/"+name;
            if(!AddListEntrie(child.c_str(),size,size,false,GetItemCount(),0,ArcArch)) return false;
            BufferOffset.push_back((u32)(DataStart+offset));
        }
    }
    return true;
}
