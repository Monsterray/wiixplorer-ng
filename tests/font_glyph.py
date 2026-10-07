#!/usr/bin/env python3
"""Production glyph conversion: padded/negative pitch, empty glyph and OOM."""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'source/FreeTypeGX.cpp').read_text();a=s.index('void FreeTypeGX::loadGlyphData(');b=s.index('\n/**',a)
code=r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include "Diagnostics/MemoryProbes.h"
using u32=uint32_t;
#define FT_PIXEL_MODE_GRAY 2
struct FT_Bitmap{unsigned rows,width;int pitch;uint8_t*buffer;unsigned pixel_mode;};
struct ftgxCharData{unsigned textureWidth=8,textureHeight=8;uint8_t*glyphDataTexture=nullptr;};
struct FreeTypeGX{void loadGlyphData(FT_Bitmap*,ftgxCharData*);};
bool fail=false;void*memalign(size_t,size_t n){return fail?nullptr:malloc(n);}void DCFlushRange(void*,int){}
'''+s[a:b]+r'''
int main(){
 FreeTypeGX font;uint8_t pixels[15];memset(pixels,0xf0,sizeof(pixels));pixels[3]=pixels[4]=0;
 FT_Bitmap bitmap{3,3,5,pixels,2};ftgxCharData glyph;font.loadGlyphData(&bitmap,&glyph);assert(glyph.glyphDataTexture && glyph.glyphDataTexture[4]==0xff);free(glyph.glyphDataTexture);glyph.glyphDataTexture=nullptr;
 bitmap.pitch=-5;bitmap.buffer=pixels+10;font.loadGlyphData(&bitmap,&glyph);assert(glyph.glyphDataTexture);free(glyph.glyphDataTexture);glyph.glyphDataTexture=nullptr;
 fail=true;font.loadGlyphData(&bitmap,&glyph);assert(!glyph.glyphDataTexture);fail=false;
 bitmap.width=1025;font.loadGlyphData(&bitmap,&glyph);assert(!glyph.glyphDataTexture);
 bitmap={0,0,0,nullptr,0};font.loadGlyphData(&bitmap,&glyph);assert(glyph.glyphDataTexture);free(glyph.glyphDataTexture);
}
'''
with tempfile.TemporaryDirectory(prefix='wx-font-glyph-') as t:
 p=Path(t);(p/'test.cpp').write_text(code)
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-g','-fsanitize=address,undefined',str(p/'test.cpp'),'-I'+str(root/'source'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('Font glyph: padded/negative pitch, empty glyphs, dimensions and OOM passed')
