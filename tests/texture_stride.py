#!/usr/bin/env python3
"""Production tiled RGB565 conversion: padded input rows and edge tiles."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root/'source/ImageOperations/TextureConverter.c').read_text()
start = source.index('u8 * RGB8ToRGB565Stride(')
end = source.index('{', start)+1
depth = 1
while depth:
    depth += (source[end] == '{')-(source[end] == '}')
    end += 1
code = r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
using u8=uint8_t;using u16=uint16_t;using u32=uint32_t;
#define ALIGN(x) (((x)+3)&~3)
size_t flushed=0;
void DCFlushRange(void*,size_t n){flushed=n;}
'''+source[start:end]+r'''
int main(){
 for(unsigned w=1;w<=9;++w)for(unsigned h=1;h<=9;++h){
  unsigned pitch=((w*3+3)&~3),capacity=ALIGN(w)*ALIGN(h)*2;
  u8 *input=new u8[pitch*h],*output=new u8[capacity];
  memset(input,0x7c,pitch*h);memset(output,0xa5,capacity);
  for(unsigned y=0;y<h;++y)memset(input+y*pitch,255,w*3);
  assert(RGB8ToRGB565Stride(input,output,w,h,pitch)==output && flushed==capacity);
  for(unsigned y=0;y<ALIGN(h);++y)for(unsigned x=0;x<ALIGN(w);++x){
   unsigned index=(y/4*(ALIGN(w)/4)+x/4)*16+(y%4)*4+x%4;
   assert(((u16*)output)[index]==(x<w && y<h?0xffff:0));
  }
  assert(!RGB8ToRGB565Stride(input,output,w,h,w*3-1));
  delete[] input;delete[] output;
 }
 u8 input[3]={},output[32]={};
 assert(!RGB8ToRGB565Stride(input,output,1025,1,3075));
 assert(!RGB8ToRGB565Stride(input,output,1,2,UINT32_MAX));
 assert(!RGB8ToRGB565Stride(nullptr,output,1,1,3));
}
'''
with tempfile.TemporaryDirectory(prefix='wx-texture-') as directory:
    tmp = Path(directory)
    (tmp/'test.cpp').write_text(code)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-g','-fsanitize=address,undefined',
                    str(tmp/'test.cpp'),'-o',str(tmp/'test')],check=True)
    subprocess.run([str(tmp/'test')],check=True)
print('Texture conversion: padded rows, 81 edge-tile shapes and invalid strides passed')
