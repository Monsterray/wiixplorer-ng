#!/usr/bin/env python3
"""Production custom font reads must fail closed on seek/read/close failures."""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
s='\n'.join(l for l in (root/'source/TextOperations/FontSystem.cpp').read_text().splitlines() if not l.startswith('#include'))
code=r'''
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <climits>
#include "Diagnostics/MemoryProbes.h"
using u8=uint8_t;using u32=uint32_t;using FT_Byte=u8;
const u8 font_ttf[]={1,2,3};const u32 font_ttf_size=3;
struct FreeTypeGX{FreeTypeGX(FT_Byte*,u32){}};
void*MEM2_alloc(u32 n){return malloc(n);}void MEM2_free(void*p){free(p);}
extern "C" void SetupPDFFallbackFont(const u8*,int){}
bool failSeek=false,failRead=false,failClose=false;
int seekFile(FILE*f,long n,int mode){return failSeek?-1:fseek(f,n,mode);}
size_t readFile(void*p,size_t n,size_t count,FILE*f){return fread(p,n,failRead?count-1:count,f);}
int closeFile(FILE*f){int ret=fclose(f);return failClose?EOF:ret;}
#define fseek seekFile
#define fread readFile
#define fclose closeFile
'''+s+r'''
int main(){FILE*f=fopen("font","wb");fwrite("abcdef",1,6,f);fclose(f);
 assert(SetupDefaultFont("font"));assert(MainFontSize==6);ClearFontData();
 failSeek=true;assert(!SetupDefaultFont("font"));assert(MainFont==font_ttf);failSeek=false;
 failRead=true;assert(!SetupDefaultFont("font"));assert(MainFont==font_ttf);failRead=false;
 failClose=true;assert(!SetupDefaultFont("font"));assert(MainFont==font_ttf);failClose=false;
 assert(!SetupDefaultFont("missing"));ClearFontData();remove("font");
}
'''
with tempfile.TemporaryDirectory(prefix='wx-font-') as t:
 p=Path(t);(p/'test.cpp').write_text(code)
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-g','-fsanitize=address,undefined',str(p/'test.cpp'),'-I'+str(root/'source'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],cwd=p,check=True)
print('Font I/O: successful custom font and seek/read/close/missing-file fallback passed')
