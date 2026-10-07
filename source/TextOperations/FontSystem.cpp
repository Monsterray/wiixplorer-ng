/****************************************************************************
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
#include "FreeTypeGX.h"
#include "Memory/mem2.h"
#include "Diagnostics/MemoryProbes.h"
#include <climits>

extern const u8 font_ttf[];
extern const u32 font_ttf_size;

FreeTypeGX * fontSystem = NULL;
static FT_Byte * MainFont = (FT_Byte *) font_ttf;
static u32 MainFontSize = font_ttf_size;

extern "C"
{
	//!Default fallback font for PDFs
	void SetupPDFFallbackFont(const u8 * font, int size);
}

void ClearFontData()
{
	if(fontSystem)
		delete fontSystem;
	fontSystem = NULL;

	if(MainFont != (FT_Byte *) font_ttf)
	{
		if(MainFont != NULL) {
			WX_MEMORY_FREE(CPU,WX_MEM_FONT,MainFont,MainFontSize);
			MEM2_free(MainFont);
		}
		MainFont = (FT_Byte *) font_ttf;
		MainFontSize = font_ttf_size;
	}
}

bool SetupDefaultFont(const char *path)
{
	bool result = false;
	FILE *pfile = NULL;

	ClearFontData();

	if(path)
		pfile = fopen(path, "rb");

    if(pfile) {
        long length=-1;
        if(fseek(pfile,0,SEEK_END)==0) length=ftell(pfile);
        if(length>0 && length<=INT_MAX-32 && fseek(pfile,0,SEEK_SET)==0) {
            MainFontSize=(u32)length;
            MainFont=(FT_Byte*)MEM2_alloc(MainFontSize);
            WX_MEMORY_ALLOC(CPU,WX_MEM_FONT,MainFont,MainFontSize);
            result=MainFont && fread(MainFont,1,MainFontSize,pfile)==MainFontSize && !ferror(pfile);
        }
        if(fclose(pfile)!=0) result=false;
        if(!result) ClearFontData();
    }

	SetupPDFFallbackFont(MainFont, MainFontSize);

	fontSystem = new FreeTypeGX(MainFont, MainFontSize);

	return result;
}
