#!/usr/bin/env python3
"""Production debug test arguments: bounds, atomic config and duplicate rejection."""
from pathlib import Path
import os,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
code=r'''
#include "Diagnostics/DebugLaunch.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
void config(const char *text){FILE *f=fopen("bench.cfg","wb");assert(f);assert(fwrite(text,1,strlen(text),f)==strlen(text));assert(fclose(f)==0);}
int main(){
 DebugBenchArguments a={};
 assert(!DebugBenchFile(a,"absent"));assert(!DebugBenchArgument(a,nullptr));
 assert(!DebugBenchArgument(a,"--unknown=sd:/test"));assert(!DebugBenchArgument(a,"--memory-bench="));
 assert(!DebugBenchArgument(a,"--memory-bench=sd:/test\n"));
 std::string large="--memory-bench="+std::string(768,'a');assert(!DebugBenchArgument(a,large.c_str()));
 assert(DebugBenchArgument(a,"--memory-bench=sd:/test"));assert(!DebugBenchArgument(a,"--memory-bench=sd:/other"));
 config("--archive-check=sd:/wiixplorer-archive-test\r\n");assert(DebugBenchFile(a,"bench.cfg"));
 assert(!strcmp(a.paths[BenchMemory],"sd:/test") && !strcmp(a.paths[BenchArchive],"sd:/wiixplorer-archive-test"));
 DebugBenchArguments b={};config("--copy-bench=sd:/copy\n--unknown=bad\n");assert(!DebugBenchFile(b,"bench.cfg"));assert(!b.paths[BenchCopy][0]);
 config("--copy-bench=sd:/copy");assert(!DebugBenchFile(b,"bench.cfg"));assert(!b.paths[BenchCopy][0]);
 config("--copy-bench=sd:/copy\n--copy-bench=sd:/other\n");assert(!DebugBenchFile(b,"bench.cfg"));assert(!b.paths[BenchCopy][0]);
 config("--storage-bench=sd:/test\n--storage-report=sd:/report\n");assert(DebugBenchFile(b,"bench.cfg"));
}
'''
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);(p/'test.cpp').write_text(code)
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-DWX_DEBUG_BUILD=1','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(ROOT/'source'),str(p/'test.cpp'),str(ROOT/'source/Diagnostics/DebugLaunch.cpp'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],cwd=p,check=True)
print('Debug test arguments: production parser bounds, CRLF, atomic failure and duplicate rejection passed')
