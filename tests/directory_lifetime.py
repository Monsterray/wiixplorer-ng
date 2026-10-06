#!/usr/bin/env python3
"""Production DirList path normalization and allocation lifetimes."""
from pathlib import Path
import os, subprocess,tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'source/FileOperations/DirList.cpp').read_text();s=s.replace('#include <sys/dirent.h>','#include <dirent.h>')
s=s.replace('#include "Tools/StringTools.h"','').replace('#include "DirList.h"','')
h=(root/'source/FileOperations/DirList.h').read_text().replace('#include <gctypes.h>','')
tools=(root/'source/Tools/StringTools.h').read_text();tools=tools[tools.index('inline void RemoveDoubleSlashs'):];tools=tools[:tools.index('#endif')]
code=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include "Diagnostics/MemoryProbes.h"
using u32=uint32_t;using u64=uint64_t;
const char *FullpathToFilename(const char*p){auto slash=strrchr(p,'/');return slash?slash+1:p;}
int strtokcmp(const char*a,const char*b,const char*){return strcmp(a,b);}
uint64_t liveBytes=0;
extern "C" void wx_memory_record(unsigned,uintptr_t p,uint64_t n,int a){if(!p)return;if(a)liveBytes+=n;else{assert(liveBytes>=n);liveBytes-=n;}}
'''+h+tools+s+r'''
int main(){mkdir("sd:",0700);FILE*f=fopen("sd:/A","wb");assert(f);fclose(f);
 {DirList d;assert(d.LoadPath("sd:///////"));assert(d.GetFilecount()==1);assert(!strcmp(d.GetFilepath(0),"sd:/A"));d.SortList();}
 assert(liveBytes==0);assert(!SortCallback({(char*)"x",false},{(char*)"X",false}));
 unlink("sd:/A");rmdir("sd:");
}
'''
with tempfile.TemporaryDirectory(prefix='wx-dir-life-') as t:
 p=Path(t);(p/'test.cpp').write_text(code)
 for level in (0,1):
  subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-g','-fsanitize=address,undefined',f'-DWX_PROBE_LEVEL={level}','-DWX_PROBE_CPU=0','-DWX_PROBE_IO=1','-I'+str(root/'source'),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
  subprocess.run([str(p/'test')],cwd=p,check=True)
print('Directory paths: normalized root, strict sort equivalence and balanced owner lifetimes passed')
