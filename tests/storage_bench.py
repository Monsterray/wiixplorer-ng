#!/usr/bin/env python3
"""Run the native benchmark logic on temporary files; check reports and ownership."""
from pathlib import Path
import os, subprocess, tempfile
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'source/Diagnostics/TransferBench.cpp').read_text()
source='\n'.join(line for line in source.splitlines() if not line.startswith('#include'))
harness=r'''
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cassert>
#include <chrono>
#include <string>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <unistd.h>
#include <zlib.h>
using u32=unsigned int;using u64=unsigned long long;
#define WX_DEBUG_BUILD 1
void *memalign(size_t a,size_t n){void *p=nullptr;return posix_memalign(&p,a,n)==0?p:nullptr;}
u64 gettime(){return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
u64 ticks_to_microsecs(u64 n){return n;}
bool canceled=false;bool wx_transfer_cancelled(){return canceled;}
enum {SD=0,USB1=3,USB8=10};
const char *DeviceName[]={"sd","gca","gcb","usb1","usb2","usb3","usb4","usb5","usb6","usb7","usb8"};
struct PartitionFS {const char *FSName="FAT32";u64 LBA_Start=2048,SecCount=100000;unsigned PartitionType=12;};
struct PartitionHandle {PartitionFS record;PartitionFS *GetPartitionRecord(int){return &record;}u32 GetSectorSize(){return 512;}};
struct DeviceHandler {
 static DeviceHandler *Instance(){static DeviceHandler d;return &d;}
 bool IsInserted(int dev){return dev==SD || dev==USB1;}
 PartitionHandle *GetSDHandle(){static PartitionHandle h;return &h;}
 PartitionHandle *GetUSBFromDev(int){return GetSDHandle();}
 int PartToPortPart(int i){return i;}
};
int CopyFile(const char *src,const char *dst,u32 size){
 FILE *a=fopen(src,"rb"),*b=fopen(dst,"wb");assert(a&&b);
 unsigned char *buffer=(unsigned char*)malloc(size);assert(buffer);size_t n;
 while((n=fread(buffer,1,size,a)))assert(fwrite(buffer,1,n,b)==n);
 assert(!ferror(a));assert(fclose(a)==0);assert(fclose(b)==0);free(buffer);return 1;
}
'''
harness+="void RunStorageBenchmark(const char*,const char* = nullptr);\n"+source+r'''
bool exists(const char *p){struct stat s;return stat(p,&s)==0;}
int main(){
 mkdir("sd:",0700);mkdir("usb1:",0700);
 assert(BenchDevice("sd:/bench")==SD && BenchDevice("usb1:/bench")==USB1 && BenchDevice("usb8:/bench")==USB8);
 assert(BenchDevice(nullptr)<0 && BenchDevice("usb:/bench")<0 && BenchDevice("usb9:/bench")<0 && BenchDevice("nand:/bench")<0 && BenchDevice("sd:/../bench")<0);
 mkdir("sd:/owned",0700);FILE *f=fopen("sd:/owned/source","wb");fputs("keep",f);fclose(f);
 RunStorageBenchmark("sd:/owned");assert(exists("sd:/owned/source") && !exists("sd:/owned/storage-benchmark.csv"));
 RunStorageBenchmark("usb8:/absent");assert(!exists("usb8:/absent"));
 for(const char *dir:{"sd:/bench","usb1:/bench"}){
  RunStorageBenchmark(dir);std::string p=std::string(dir)+"/storage-benchmark.csv";f=fopen(p.c_str(),"rb");assert(f);
  char line[256];assert(fgets(line,sizeof(line),f));int rows=0;
  while(fgets(line,sizeof(line),f)){char op[16];unsigned block,repeat,bytes,verified;u64 us;
   assert(sscanf(line,"%15[^,],%u,%u,%u,%llu,%u",op,&block,&repeat,&bytes,&us,&verified)==6);
   assert(bytes==8388608 && verified==1 && us>0 && repeat<3);++rows;
  }fclose(f);assert(rows==12);
  assert(!exists((std::string(dir)+"/source").c_str()) && !exists((std::string(dir)+"/destination").c_str()));
  assert(exists((std::string(dir)+"/storage-metadata.csv").c_str()));
  f=fopen((std::string(dir)+"/storage-complete").c_str(),"rb");assert(f && fgetc(f)=='1');fclose(f);
 }
 RunStorageBenchmark("usb1:/separate","sd:/usb-report");assert(!exists("usb1:/separate") && exists("sd:/usb-report/storage-benchmark.csv"));
 RunStorageBenchmark("usb1:/refuse","sd:/owned");assert(!exists("usb1:/refuse") && exists("sd:/owned/source"));
 canceled=true;RunStorageBenchmark("sd:/canceled");assert(!exists("sd:/canceled/source"));
 f=fopen("sd:/canceled/storage-benchmark.csv","rb");assert(f);char line[256];fgets(line,sizeof(line),f);assert(fgets(line,sizeof(line),f));assert(strstr(line,",0\n"));assert(!fgets(line,sizeof(line),f));fclose(f);
 f=fopen("sd:/canceled/storage-complete","rb");assert(f && fgetc(f)=='0');fclose(f);
}
'''
with tempfile.TemporaryDirectory(prefix='wx-storage-check-') as tmp:
    p=Path(tmp);(p/'test.cpp').write_text(harness)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-fsanitize=address,undefined',str(p/'test.cpp'),'-lz','-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],cwd=p,check=True,timeout=30)
print('Storage benchmark: SD/USB reports, CRC verification, private directory ownership, absent device, cancellation cleanup passed')
