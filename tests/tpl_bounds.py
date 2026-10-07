#!/usr/bin/env python3
"""Production TPL metadata parsing, endian and range regressions."""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
def stripped(p):return '\n'.join(l for l in (root/p).read_text().splitlines() if not l.startswith('#include'))
code=r'''
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <vector>
#include <new>
using u8=uint8_t;using u16=uint16_t;using u32=uint32_t;using f32=float;using gdImagePtr=void*;
enum{GX_TF_I4=0,GX_TF_I8=1,GX_TF_IA4=2,GX_TF_IA8=3,GX_TF_RGB565=4,GX_TF_RGB5A3=5,GX_TF_RGBA8=6,GX_TF_CI4=8,GX_TF_CI8=9,GX_TF_CI14=10,GX_TF_CMPR=14};
void LoadFileToMem(const char*,u8**,u32*){}
#define CONVERT(n) bool n(const u8*,int,int,gdImagePtr*){return false;}
CONVERT(RGB565ToGD) CONVERT(RGB565A3ToGD) CONVERT(RGBA8ToGD) CONVERT(I4ToGD) CONVERT(I8ToGD) CONVERT(IA4ToGD) CONVERT(IA8ToGD) CONVERT(CMPToGD)
'''+stripped('source/ImageOperations/TplImage.h')+stripped('source/ImageOperations/TplImage.cpp')+r'''
void be(std::vector<u8>&b,unsigned p,u32 n){b[p]=n>>24;b[p+1]=n>>16;b[p+2]=n>>8;b[p+3]=n;}
int main(){
 {u8 tiny[1]={0};TplImage t(tiny,1);assert(!t.GetTextureBuffer(0));}
 std::vector<u8>b(120);be(b,0,0x0020af30);be(b,4,1);be(b,8,12);be(b,12,20);b[21]=4;b[23]=4;be(b,24,GX_TF_RGBA8);be(b,28,56);
 TplImage t(b.data(),b.size());assert(t.GetWidth(0)==4 && t.GetTextureSize(0)==64 && t.GetTextureBuffer(0));assert(!t.GetTextureBuffer(1));
 for(unsigned n=0;n<b.size();++n){TplImage cut(b.data(),n);assert(!cut.GetTextureBuffer(0));}
 auto bad=b;be(bad,12,0xfffffff0);assert(!t.LoadImage(bad.data(),bad.size()));assert(!t.GetTextureBuffer(0));
 bad=b;be(bad,4,0xffffffff);assert(!t.LoadImage(bad.data(),bad.size()));
 bad=b;be(bad,28,100);assert(!t.LoadImage(bad.data(),bad.size()));
 bad=b;b[21]=0;assert(!t.LoadImage(b.data(),b.size()));
 bad=b;be(bad,24,99);assert(!t.LoadImage(bad.data(),bad.size()));
}
'''
with tempfile.TemporaryDirectory(prefix='wx-tpl-') as t:
 p=Path(t);(p/'test.cpp').write_text(code)
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-g','-fsanitize=address,undefined',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('TPL: truncated headers/data, big-endian metadata, invalid counts/offsets/dimensions and failed reload passed')
