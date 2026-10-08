#!/usr/bin/env python3
"""Production image/text/screenshot I/O rejects failed writes and preserves files."""
from pathlib import Path
import os,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
def function(path,signature):
    text=(ROOT/path).read_text();start=text.index(signature);body=text.index('{',start);level=1;end=body+1
    while level:
        level += (text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]
with tempfile.TemporaryDirectory(prefix='wx-feature-') as directory:
    root=Path(directory);(root/'Tools').mkdir()
    (root/'gctypes.h').write_text('#include <stdbool.h>\ntypedef unsigned char u8;\n')
    (root/'Tools/tools.h').write_text('#define LIMIT(v,a,b) ((v)<(a)?(a):(v)>(b)?(b):(v))\n')
    gd='''#pragma once
#include <stdio.h>
struct image { int sx,sy; };typedef image *gdImagePtr;
extern bool emptyOutput;
static inline void encode(gdImagePtr,FILE *f) { if(!emptyOutput) fwrite("encoded",1,7,f); }
'''
    for name in ('Png','Gif','Gd'):gd+=f'static inline void gdImage{name}(gdImagePtr p,FILE *f) {{ encode(p,f); }}\n'
    gd+='static inline void gdImageTiff(gdImagePtr p,FILE *f) {encode(p,f);fflush(f);rewind(f);char c;fread(&c,1,1,f);fseek(f,0,SEEK_END); }\n'
    for name in ('Jpeg','Bmp'):gd+=f'static inline void gdImage{name}(gdImagePtr p,FILE *f,int) {{ encode(p,f); }}\n'
    gd+='static inline void gdImageGd2(gdImagePtr p,FILE *f,int,int) {encode(p,f);}\n'
    (root/'gd.h').write_text(gd)
    code=r'''
#include <stdio.h>
#include <string>
#include <cstring>
#include <cassert>
#include <cstdlib>
#include "gctypes.h"
#include "gd.h"
#include "ImageOperations/ImageWrite.h"
#include "FileOperations/TransferFile.h"
bool emptyOutput=false,failClose=false;unsigned errors=0;
int testClose(FILE *f) {int result=fclose(f);return failClose ? -1 : result;}
#define fclose testClose
struct Text { std::string value;const std::string &toUTF8(){return value;} };
struct TextEditor {Text *MainFileTxt;void WriteTextFile(const std::string &);};
void ShowError(const char*){++errors;}
#define tr(x) (x)
'''+function('source/TextOperations/TextEditor.cpp','void TextEditor::WriteTextFile(')+r'''
void write(const char *path,const char *text){FILE *f=fopen(path,"wb");assert(f && fwrite(text,1,strlen(text),f)==strlen(text));fclose(f);}
std::string contents(const char *path){FILE *f=fopen(path,"rb");assert(f);char data[128];size_t n=fread(data,1,sizeof(data),f);fclose(f);return std::string(data,n);}
int main(){
 image im={5,3};Text text={"first\n\xce\xa9\n"};TextEditor editor={&text};
 write("original","old");editor.WriteTextFile("original");assert(contents("original")==text.value);
 write("original","old");failClose=true;editor.WriteTextFile("original");failClose=false;
 assert(contents("original")=="old" && errors==1);
 assert(WriteGDImage("original",&im,IMAGE_PNG,0) && contents("original")=="encoded");
 assert(WriteGDImage("original",&im,IMAGE_TIFF,0) && contents("original")=="encoded");
 write("original","old");emptyOutput=true;assert(!WriteGDImage("original",&im,IMAGE_GD2,0));emptyOutput=false;
 assert(contents("original")=="old");failClose=true;assert(!WriteGDImage("original",&im,IMAGE_PNG,0));failClose=false;
 assert(contents("original")=="old" && !WriteGDImage(nullptr,&im,0,0) && !WriteGDImage("original",&im,255,0));
}
'''
    # Apply the close-failure shim to production encoder compilation too.
    writer=(ROOT/'source/ImageOperations/ImageWrite.c').read_text().replace('#include "Tools/tools.h"','#include "Tools/tools.h"\nextern int testClose(FILE*);\n#define fclose testClose')
    (root/'write.cpp').write_text(writer);(root/'test.cpp').write_text(code)
    compiler=os.environ.get('CXX','c++')
    subprocess.run([compiler,'-std=c++11','-fsanitize=address,undefined','-I'+str(root),'-I'+str(ROOT/'source'),'-I'+str(ROOT/'source/ImageOperations'),str(root/'test.cpp'),str(root/'write.cpp'),'-o',str(root/'test')],check=True)
    subprocess.run([str(root/'test')],cwd=root,check=True)
print('Feature I/O: exact UTF-8 bytes, empty encoder/close failure rejection and staged original preservation passed')
