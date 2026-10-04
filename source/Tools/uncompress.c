/***************************************************************************
 * Copyright (C) 2010
 * by Dimok
 *
 * This software is provided 'as-is', without any express or implied
 * warranty. In no event will the authors be held liable for any
 * damages arising from the use of this software.
 *
 * Permission is granted to anyone to use this software for any
 * purpose, including commercial applications, and to alter it and
 * redistribute it freely, subject to the following restrictions:
 *
 * 1. The origin of this software must not be misrepresented; you
 * must not claim that you wrote the original software. If you use
 * this software in a product, an acknowledgment in the product
 * documentation would be appreciated but is not required.
 *
 * 2. Altered source versions must be plainly marked as such, and
 * must not be misrepresented as being the original software.
 *
 * 3. This notice may not be removed or altered from any source
 * distribution.
 *
 * for WiiXplorer 2010
 ***************************************************************************/
#include <malloc.h>
#include <string.h>

#include "uncompress.h"

// NG alteration: all input/output accesses and dictionary runs are bounded.
#include "ArchiveOperations/ArchiveSafety.h"

static u32 read_be32(const u8 *p)
{
    return ((u32)p[0]<<24)|((u32)p[1]<<16)|((u32)p[2]<<8)|p[3];
}

u8 *uncompressLZ77(const u8 *in,u32 length,u32 *size)
{
    if(size) *size=0;
    if(!in || !size || length<8 || memcmp(in,"LZ77",4) || in[4]!=0x10) return NULL;
    u32 total=in[5]|((u32)in[6]<<8)|((u32)in[7]<<16);
    if(!total || total>wx_archive_memory_budget()) return NULL;
    u8 *out=(u8*)malloc(total);
    if(!out) return NULL;
    u32 src=8,dst=0;
    while(dst<total) {
        if(src>=length) goto fail;
        u8 flags=in[src++];
        for(unsigned bit=0;bit<8 && dst<total;++bit,flags<<=1) {
            if(flags&0x80) {
                if(length-src<2) goto fail;
                unsigned run=(in[src]>>4)+3;
                unsigned distance=(((in[src]&15)<<8)|in[src+1])+1;
                src+=2;
                if(distance>dst || run>total-dst) goto fail;
                // Forward byte copies implement overlapping LZ dictionary runs.
                while(run--) { out[dst]=out[dst-distance]; ++dst; }
            } else {
                if(src>=length) goto fail;
                out[dst++]=in[src++];
            }
        }
    }
    *size=total;
    return out;
fail:
    free(out);
    return NULL;
}

int uncompressYaz0(const u8 *in,u32 length,u8 *out,u32 total)
{
    if(!in || !out || length<16 || memcmp(in,"Yaz0",4) || read_be32(in+4)!=total) return 0;
    u32 src=16,dst=0;
    while(dst<total) {
        if(src>=length) return 0;
        u8 flags=in[src++];
        for(unsigned bit=0;bit<8 && dst<total;++bit,flags<<=1) {
            if(flags&0x80) {
                if(src>=length) return 0;
                out[dst++]=in[src++];
            } else {
                if(length-src<2) return 0;
                unsigned run=in[src]>>4;
                unsigned distance=(((in[src]&15)<<8)|in[src+1])+1;
                src+=2;
                if(!run) { if(src>=length) return 0; run=in[src++]+18; }
                else run+=2;
                if(distance>dst || run>total-dst) return 0;
                while(run--) { out[dst]=out[dst-distance]; ++dst; }
            }
        }
    }
    return 1;
}

u32 CheckIMD5Type(const u8 *buffer,int length)
{
    if(!buffer || length<4) return 0;
    if(memcmp(buffer,"IMD5",4)) return read_be32(buffer);
    if(length<36) return 0;
    const u8 *file=buffer+32;
    if(memcmp(file,"LZ77",4)) return read_be32(file);
    u32 size=0;
    u8 *out=uncompressLZ77(file,length-32,&size);
    if(!out) return 0;
    u32 type=size>=4 ? read_be32(out) : 0;
    free(out);
    return type;
}
