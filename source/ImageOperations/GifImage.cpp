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
#include <gccore.h>
#include <malloc.h>
#include <memory>
#include <new>
#include <algorithm>
#include "Memory/mem2.h"
#include "Diagnostics/MemoryProbes.h"
#include <string.h>
#include "VideoOperations/video.h"
#include "Language/gettext.h"
#include "Tools/tools.h"
#include "GifImage.hpp"


typedef struct _GIFLSDtag
{
	u16 ScreenWidth;
	u16 ScreenHeight;
	u8 PackedFields;
	u8 Background;
	u8 PixelAspectRatio;
} __attribute__((__packed__)) GIFLSDtag;

typedef struct _GIFGCEtag
{
	u8 BlockSize;	   // Block Size: 4 bytes
	u8 PackedFields;
	u16 Delay;		  // Delay Time (1/100 seconds)
	u8 Transparent;	 // Transparent Color Index
} __attribute__((__packed__)) GIFGCEtag;

// Read Image Descriptor
typedef struct _GIFIDtag
{
	u16 xPos;
	u16 yPos;
	u16 Width;
	u16 Height;
	u8 PackedFields;
} __attribute__((__packed__)) GIFIDtag;

typedef struct
{
	u8 b,g,r,a;
} __attribute__((__packed__)) GIFCOLOR;


GifImage::GifImage(const u8 * img, int imgSize)
{
	currentFrame = 0;
	lastTimer = 0.0f;
	LoadImage(img, imgSize);
}

GifImage::~GifImage() { ClearFrames(); }

u8 * GifImage::GetFrameImage(int pos)
{
	if(pos < 0 || pos >= GetFrameCount())
		return NULL;

	return Frames[pos].image;
}

// GIF89a LZW, with bytewise bounded code reads and fixed-size dictionary.
// See https://www.w3.org/Graphics/GIF/spec-gif89a.txt (deferred clear codes).
struct GifLzwTables { u16 prefix[4096]; u8 suffix[4096], stack[4096]; };
static bool LZWDecoder(const u8 *input,size_t bytes,u8 *out,unsigned initial,
                       unsigned stride,unsigned width,unsigned height,bool interlace,GifLzwTables &workspace)
{
    if(!input || !out || initial<2 || initial>8 || !width || !height || stride<width) return false;
    GifLzwTables *table=&workspace;
    unsigned clear=1u<<initial,end=clear+1,next=end+1,bits=initial+1;
    int previous=-1; unsigned first=0,pixels=0,row=0,col=0,pass=0;
    size_t bit=0;
    const unsigned starts[]={0,4,2,1},steps[]={8,8,4,2};
    for(;;) {
        size_t position=bit/8; unsigned shift=bit&7,need=(shift+bits+7)/8,word=0;
        if(position>bytes || need>bytes-position) return false;
        for(unsigned j=0;j<need;++j) word|=(unsigned)input[position+j]<<(8*j);
        unsigned code=(word>>shift)&((1u<<bits)-1); bit+=bits;
        if(code==end) return pixels==width*height;
        if(code==clear) { next=end+1;bits=initial+1;previous=-1;continue; }
        unsigned original=code,n=0;
        if(previous<0) { if(code>=clear) return false; }
        else if(code==next && next<4096) { table->stack[n++]=first;code=previous; }
        else if(code>=next) return false;
        while(code>=end+1) {
            if(code>=next || n>=4095) return false;
            table->stack[n++]=table->suffix[code];code=table->prefix[code];
        }
        if(code>=clear || n>=4096) return false;
        first=code;table->stack[n++]=first;
        if(previous>=0 && next<4096) {
            table->prefix[next]=previous;table->suffix[next]=first;++next;
            if(next==(1u<<bits) && bits<12) ++bits;
        }
        previous=original;
        if(n>width*height-pixels) return false;
        while(n) {
            if(col==width) {
                col=0;row+=interlace ? steps[pass] : 1;
                if(interlace) while(row>=height && pass<3) row=starts[++pass];
            }
            if(row>=height) return false;
            out[row*stride+col++]=table->stack[--n];++pixels;
        }
    }
}

static u16 GifLE16(const u8 *p) { return p[0]|((u16)p[1]<<8); }
static bool GifBlocks(const u8 *img,size_t size,size_t &pos,std::vector<u8> *data,size_t budget)
{
    size_t end=pos,total=0;
    while(end<size) {
        unsigned n=img[end++];
        if(!n) {
            if(data) {
                // Include the old allocation during reserve's replacement.
                size_t old=data->capacity();
                if(old>budget || (total>old && total>budget-old)) return false;
                data->clear();data->reserve(total);
                if(data->capacity()>budget) return false;
                while(pos<end-1) { unsigned block=img[pos++];data->insert(data->end(),img+pos,img+pos+block);pos+=block; }
            }
            pos=end;return true;
        }
        if(n>size-end || (data && (total>budget || n>budget-total))) return false;
        total+=n;end+=n;
    }
    return false;
}
void GifImage::ClearFrames()
{
    for(size_t i=0;i<Frames.size();++i) {
        WX_MEMORY_FREE(GPU,WX_MEM_GIF_FRAME,Frames[i].image,datasizeRGBA8(Frames[i].width,Frames[i].height));
        free(Frames[i].image);
    }
    Frames.clear();MainWidth=MainHeight=0;currentFrame=0;lastTimer=0;
}
void GifImage::LoadImage(const u8 *img,int imgSize)
{
    ClearFrames();
    if(!img || imgSize<13 || (memcmp(img,"GIF87a",6) && memcmp(img,"GIF89a",6))) return;
    size_t size=imgSize,pos=13;
    MainWidth=GifLE16(img+6);MainHeight=GifLE16(img+8);
    if(!MainWidth || !MainHeight || MainWidth>1024 || MainHeight>1024) { ClearFrames();return; }
    GIFCOLOR global[256]={};
    unsigned globalCount=1u<<((img[10]&7)+1);
    if(img[10]&0x80) {
        if(3*globalCount>size-pos) { ClearFrames();return; }
        for(unsigned i=0;i<globalCount;++i) {global[i].r=img[pos++];global[i].g=img[pos++];global[i].b=img[pos++];}
    } else {
        globalCount=256;
        for(unsigned i=0;i<256;++i) global[i].r=global[i].g=global[i].b=i;
    }
    // Conservative decoded/workspace allowance; checked allocation still decides.
    const u64 available=(u64)mallinfo().fordblks+MEM2_freesize();
    const size_t budget=(size_t)std::min<u64>(16u*1024u*1024u,available/2);
    size_t used=0;
    unsigned delay=0,disposal=0;int transparent=-1;
    bool complete=false;
    std::vector<u8> compressed;
    std::unique_ptr<u8[]> raster;
    size_t rasterCapacity=0;
    std::unique_ptr<GifLzwTables> table(new(std::nothrow) GifLzwTables);
    WX_MEMORY_BUFFER(CPU,WX_MEM_GIF_WORKSPACE,table.get(),sizeof(GifLzwTables));
    if(!table) { ClearFrames();return; }
    try {
        while(pos<size) {
            unsigned tag=img[pos++];
            if(tag==0x3b) { complete=true;break; }
            if(tag==0x21) {
                if(pos>=size) break;
                unsigned kind=img[pos++];
                if(kind==0xf9) {
                    if(size-pos<6 || img[pos]!=4 || img[pos+5]!=0) break;
                    unsigned flags=img[pos+1];delay=GifLE16(img+pos+2);disposal=(flags>>2)&7;
                    transparent=(flags&1) ? img[pos+4] : -1;pos+=6;
                } else if(!GifBlocks(img,size,pos,NULL,0)) break;
                continue;
            }
            if(tag!=0x2c || size-pos<9 || Frames.size()>=4096) break;
            GifFrame frame={};
            frame.offsetx=GifLE16(img+pos);frame.offsety=GifLE16(img+pos+2);
            unsigned w=GifLE16(img+pos+4),h=GifLE16(img+pos+6),flags=img[pos+8];pos+=9;
            if(!w || !h || w>(unsigned)MainWidth || h>(unsigned)MainHeight ||
               (unsigned)frame.offsetx>(unsigned)MainWidth-w || (unsigned)frame.offsety>(unsigned)MainHeight-h) break;
            frame.width=ALIGN(w);frame.height=ALIGN(h);frame.Delay=delay;frame.Disposal=disposal;frame.Transparent=transparent>=0;
            GIFCOLOR palette[256];unsigned colors=globalCount;memcpy(palette,global,sizeof(palette));
            if(flags&0x80) {
                colors=1u<<((flags&7)+1);if(3*colors>size-pos) break;
                for(unsigned i=0;i<colors;++i) {palette[i].r=img[pos++];palette[i].g=img[pos++];palette[i].b=img[pos++];}
            }
            if(pos>=size) break;
            unsigned initial=img[pos++];
            const size_t frameBytes=datasizeRGBA8(frame.width,frame.height),rasterBytes=(size_t)frame.width*h;
            size_t nextCapacity=Frames.capacity();
            if(Frames.size()==nextCapacity) nextCapacity=std::min<size_t>(4096,std::max<size_t>(1,nextCapacity*2));
            size_t metadata=(nextCapacity+(nextCapacity>Frames.capacity() ? Frames.capacity() : 0))*sizeof(GifFrame);
            size_t fixed=frameBytes+metadata+sizeof(GifLzwTables)+std::max(rasterBytes,rasterCapacity);
            if(used>budget || fixed>budget-used) break;
            if(!GifBlocks(img,size,pos,&compressed,budget-used-fixed)) break;
            if(rasterBytes>rasterCapacity) {
                if(rasterCapacity>budget-used-fixed-compressed.capacity()) break;
                std::unique_ptr<u8[]> next(new(std::nothrow) u8[rasterBytes]);
                if(!next) break;
                raster.swap(next);rasterCapacity=rasterBytes;
            }
            if(!LZWDecoder(compressed.data(),compressed.size(),raster.get(),initial,frame.width,w,h,(flags&0x40)!=0,*table)) break;
            frame.image=(u8*)memalign(32,frameBytes);
            WX_MEMORY_ALLOC(GPU,WX_MEM_GIF_FRAME,frame.image,frameBytes);
            if(!frame.image) break;
            bool okay=true;
            for(unsigned y=0;y<(unsigned)frame.height;++y) for(unsigned x=0;x<(unsigned)frame.width;++x) {
                u32 offset=coordsRGBA8(x,y,frame.width);unsigned index=x<w && y<h ? raster[y*frame.width+x] : 0;
                if(x<w && y<h && index>=colors) okay=false;
                frame.image[offset]=(x<w && y<h && (int)index!=transparent) ? 255 : 0;
                frame.image[offset+1]=palette[index].r;frame.image[offset+32]=palette[index].g;frame.image[offset+33]=palette[index].b;
            }
            if(!okay) { WX_MEMORY_FREE(GPU,WX_MEM_GIF_FRAME,frame.image,frameBytes);free(frame.image);break; }
            DCFlushRange(frame.image,frameBytes);
            try { Frames.reserve(nextCapacity);Frames.push_back(frame); }
            catch(const std::bad_alloc &) { WX_MEMORY_FREE(GPU,WX_MEM_GIF_FRAME,frame.image,frameBytes);free(frame.image);throw; }
            used+=frameBytes;delay=disposal=0;transparent=-1;
        }
    } catch(const std::bad_alloc &) {}
    if(!complete) ClearFrames();
}

void GifImage::Draw(int x, int y, int z, int degrees, float scaleX, float scaleY, int alpha, int minwidth, int maxwidth, int minheight, int maxheight)
{
	if(Frames.size() == 0)
		return;

	float OffX, OffY;

	for(u32 i = 0; i < RedrawQueue.size(); i++)
	{
		 //!Correcting scale position
		OffX = x+RedrawQueue[i].offsetx*scaleX+(RedrawQueue[i].width*scaleX-RedrawQueue[i].width)/2.0f-(MainWidth*scaleX-MainWidth)/2.0f;
		OffY = y+RedrawQueue[i].offsety*scaleY+(RedrawQueue[i].height*scaleY-RedrawQueue[i].height)/2.0f-(MainHeight*scaleY-MainHeight)/2.0f;

		Menu_DrawImgCut(RedrawQueue[i].image, RedrawQueue[i].width, RedrawQueue[i].height,
						GX_TF_RGBA8, OffX, OffY, z, degrees, scaleX, scaleY, alpha, minwidth,
						maxwidth, minheight, maxheight);
	}

	//!Correcting scale position
	OffX = x+Frames[currentFrame].offsetx*scaleX+(Frames[currentFrame].width*scaleX-Frames[currentFrame].width)/2.0f-(MainWidth*scaleX-MainWidth)/2.0f;
	OffY = y+Frames[currentFrame].offsety*scaleY+(Frames[currentFrame].height*scaleY-Frames[currentFrame].height)/2.0f-(MainHeight*scaleY-MainHeight)/2.0f;

	Menu_DrawImgCut(Frames[currentFrame].image, Frames[currentFrame].width, Frames[currentFrame].height,
					GX_TF_RGBA8, OffX, OffY, z, degrees, scaleX, scaleY, alpha, minwidth, maxwidth, minheight,
					maxheight);

	if(DelayTimer.elapsed()-lastTimer >= Frames[currentFrame].Delay/100.0f)
	{
		if((Frames[currentFrame].Disposal == 0 && !Frames[currentFrame].Transparent) ||
			Frames[currentFrame].Disposal == 1)
		{
			RedrawQueue.push_back(Frames[currentFrame]);
		}
		else if(Frames[currentFrame].Disposal == 2 && RedrawQueue.size() > 0)
		{
			RedrawQueue.pop_back();
		}

		++currentFrame;

		lastTimer = DelayTimer.elapsed();

		if(currentFrame >= (int) Frames.size())
		{
			currentFrame = 0;
			RedrawQueue.clear();
		}
	}
}
