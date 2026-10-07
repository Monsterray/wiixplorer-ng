/***************************************************************************
 * Copyright (C) 2010
 * Dimok
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
 * TplImage.cpp
 *
 * for WiiXplorer 2010
 ***************************************************************************/
#include <gccore.h>
#include <malloc.h>
#include <string.h>
#include <new>
#include "FileOperations/fileops.h"
#include "TextureConverter.h"
#include "TplImage.h"

TplImage::TplImage(const char * filepath)
{
	TPLBuffer = NULL;
	TPLSize = 0;

	u8 * buffer = NULL;
	u32 filesize = 0;
	LoadFileToMem(filepath, &buffer, &filesize);

	if(buffer)
	{
		LoadImage(buffer, filesize);
		free(buffer);
	}
}

TplImage::TplImage(const u8 * imgBuffer, u32 imgSize)
{
	TPLBuffer = NULL;
	TPLSize = 0;

	if(imgBuffer)
	{
		LoadImage(imgBuffer, imgSize);
	}
}

TplImage::~TplImage()
{
	if(TPLBuffer)
		free(TPLBuffer);

	TextureHeader.clear();
}

static u32 TplBE32(const u8 *p)
{
    return ((u32)p[0]<<24)|((u32)p[1]<<16)|((u32)p[2]<<8)|p[3];
}

bool TplImage::LoadImage(const u8 *imgBuffer, u32 imgSize)
{
    free(TPLBuffer); TPLBuffer=NULL; TPLSize=0; TextureHeader.clear();
    if(!imgBuffer || imgSize<12) return false;
    TPLBuffer=(u8*)malloc(imgSize);
    if(!TPLBuffer) return false;
    TPLSize=imgSize; memcpy(TPLBuffer,imgBuffer,imgSize);
    bool okay=false;
    try { okay=ParseTplFile(); } catch(const std::bad_alloc &) {}
    if(!okay) { free(TPLBuffer); TPLBuffer=NULL; TPLSize=0; TextureHeader.clear(); }
    return okay;
}

bool TplImage::ParseTplFile()
{
    if(!TPLBuffer || TPLSize<12 || TplBE32(TPLBuffer)!=0x0020af30 ||
       TplBE32(TPLBuffer+8)!=12) return false;
    u32 count=TplBE32(TPLBuffer+4);
    // Defensive metadata ceiling: <=144 KiB descriptors, not a payload limit.
    if(!count || count>4096 || count>(TPLSize-12)/8) return false;
    TextureHeader.reserve(count);
    for(u32 i=0;i<count;++i) {
        u32 offset=TplBE32(TPLBuffer+12+8*i);
        if(offset<12+8*count || offset>TPLSize || sizeof(TPL_Texture_Header)>TPLSize-offset) return false;
        const u8 *p=TPLBuffer+offset;
        TPL_Texture_Header h={};
        h.height=((u16)p[0]<<8)|p[1]; h.width=((u16)p[2]<<8)|p[3];
        h.format=TplBE32(p+4); h.offset=TplBE32(p+8);
        // GX_InitTexObj dimensions are 1..1024; reject unsupported palettes.
        if(!h.width || !h.height || h.width>1024 || h.height>1024 ||
           h.format==GX_TF_CI4 || h.format==GX_TF_CI8 || h.format==GX_TF_CI14) return false;
        TextureHeader.push_back(h);
        int bytes=GetTextureSize(i);
        if(bytes<=0 || h.offset<offset+sizeof(TPL_Texture_Header) || h.offset>TPLSize ||
           (u32)bytes>TPLSize-h.offset) return false;
    }
    return true;
}

int TplImage::GetWidth(int pos)
{
	if(pos < 0 || pos >= (int) TextureHeader.size())
	{
		return 0;
	}

	return TextureHeader[pos].width;
}

int TplImage::GetHeight(int pos)
{
	if(pos < 0 || pos >= (int) TextureHeader.size())
	{
		return 0;
	}

	return TextureHeader[pos].height;
}

u32 TplImage::GetFormat(int pos)
{
	if(pos < 0 || pos >= (int) TextureHeader.size())
	{
		return 0;
	}

	return TextureHeader[pos].format;
}

const u8 * TplImage::GetTextureBuffer(int pos)
{
	if(pos < 0 || pos >= (int) TextureHeader.size())
	{
		return 0;
	}

	return TPLBuffer + TextureHeader[pos].offset;
}

int TplImage::GetTextureSize(int pos)
{
	int width = GetWidth(pos);
	int height = GetHeight(pos);
	int len = 0;

	switch(GetFormat(pos))
	{
			case GX_TF_I4:
			case GX_TF_CI4:
			case GX_TF_CMPR:
				len = ((width+7)>>3)*((height+7)>>3)*32;
				break;
			case GX_TF_I8:
			case GX_TF_IA4:
			case GX_TF_CI8:
				len = ((width+7)>>3)*((height+3)>>2)*32;
				break;
			case GX_TF_IA8:
			case GX_TF_CI14:
			case GX_TF_RGB565:
			case GX_TF_RGB5A3:
				len = ((width+3)>>2)*((height+3)>>2)*32;
				break;
			case GX_TF_RGBA8:
				len = ((width+3)>>2)*((height+3)>>2)*32*2;
				break;
			default:
				len = 0;
				break;
	}

	return len;
}

gdImagePtr TplImage::ConvertToGD(int pos)
{
	if(pos < 0 || pos >= (int) TextureHeader.size())
	{
		return 0;
	}

	gdImagePtr gdImg = 0;

	switch(TextureHeader[pos].format)
	{
		case GX_TF_RGB565:
			RGB565ToGD(GetTextureBuffer(pos), TextureHeader[pos].width, TextureHeader[pos].height, &gdImg);
			break;
		case GX_TF_RGB5A3:
			RGB565A3ToGD(GetTextureBuffer(pos), TextureHeader[pos].width, TextureHeader[pos].height, &gdImg);
			break;
		case GX_TF_RGBA8:
			RGBA8ToGD(GetTextureBuffer(pos), TextureHeader[pos].width, TextureHeader[pos].height, &gdImg);
			break;
		case GX_TF_I4:
			I4ToGD(GetTextureBuffer(pos), TextureHeader[pos].width, TextureHeader[pos].height, &gdImg);
			break;
		case GX_TF_I8:
			I8ToGD(GetTextureBuffer(pos), TextureHeader[pos].width, TextureHeader[pos].height, &gdImg);
			break;
		case GX_TF_IA4:
			IA4ToGD(GetTextureBuffer(pos), TextureHeader[pos].width, TextureHeader[pos].height, &gdImg);
			break;
		case GX_TF_IA8:
			IA8ToGD(GetTextureBuffer(pos), TextureHeader[pos].width, TextureHeader[pos].height, &gdImg);
			break;
		case GX_TF_CMPR:
			CMPToGD(GetTextureBuffer(pos), TextureHeader[pos].width, TextureHeader[pos].height, &gdImg);
			break;
		default:
			gdImg = 0;
			break;
	}

	return gdImg;
}
