#!/usr/bin/env python3
"""Production PDF geometry checks, before float-to-integer conversion/allocation."""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
code=r'''
#include <cassert>
#include <cmath>
#include "TextOperations/PdfRaster.h"
int main(){
 int w=0,h=0;assert(WxPdfRaster(0,0,612,792,8*1024*1024,w,h) && w==612 && h==792);
 assert(WxPdfRaster(-.5,-.5,3,3,96,w,h) && w==4 && h==4);
 assert(!WxPdfRaster(0,0,3,3,95,w,h));
 assert(!WxPdfRaster(0,0,1025,1,8*1024*1024,w,h));
 assert(!WxPdfRaster(0,0,INFINITY,3,SIZE_MAX,w,h));
 assert(!WxPdfRaster(NAN,0,3,3,SIZE_MAX,w,h));
 assert(!WxPdfRaster(3,3,0,0,SIZE_MAX,w,h));
 assert(!WxPdfRaster(-3e20,-3e20,3e20,3e20,SIZE_MAX,w,h));
 assert(!WxPdfRaster(2147483648.f,0,2147483648.f,1,SIZE_MAX,w,h));
}
'''
with tempfile.TemporaryDirectory(prefix='wx-pdf-raster-') as t:
 p=Path(t);(p/'test.cpp').write_text('#include <cstdint>\n'+code)
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-fsanitize=address,undefined',str(p/'test.cpp'),'-I'+str(root/'source'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('PDF raster: finite coordinates, integer/GX bounds, padding and combined pixmap/texture capacity passed')
