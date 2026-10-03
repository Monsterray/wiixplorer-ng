#!/usr/bin/env python3
"""Check production FTP listing allocation failure, ownership and name bounds."""
from pathlib import Path
import os,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'source/FTPOperations/ftp_devoptab.c').read_text()
def function(signature):
    start=source.index(signature);end=source.index('{',start)+1;depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]
code=r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cerrno>
#include <sys/types.h>
using u64=uint64_t;using u32=uint32_t;
#define UNUSED __attribute__((unused))
#define NET_ASSERT(x) assert(x)
#define NET_PRINTF(...) ((void)0)
struct FTPDIRENTRY{off_t size;bool isDirectory;char name[256];};
struct FTPDIRENTRYLISTITEM{FTPDIRENTRY item;void *next;};
struct FTPDIRSTATESTRUCT{FTPDIRENTRYLISTITEM *list=nullptr,*next_enum_item=nullptr;};
bool failAllocation=false;
FTPDIRENTRYLISTITEM *allocate(size_t size){return failAllocation?nullptr:(FTPDIRENTRYLISTITEM*)malloc(size);}
#define malloc allocate
'''
for signature in ('static void freeDirList(','static bool AddDirEntry(','static void FTP_FindClose(','static bool copyDirList(','static u64 mystrtoul64('):
    code+=function(signature)+'\n'
code+=r'''
#undef malloc
int main(){
 FTPDIRSTATESTRUCT state;FTPDIRENTRYLISTITEM **tail=&state.list;
 failAllocation=true;assert(!AddDirEntry(&state,&tail,"file",1,false)&&errno==ENOMEM&&!state.list);
 failAllocation=false;char longName[257];memset(longName,'x',256);longName[256]=0;
 assert(!AddDirEntry(&state,&tail,longName,1,false)&&errno==ENAMETOOLONG&&!state.list);
 longName[255]=0;assert(AddDirEntry(&state,&tail,longName,1,false));
 FTPDIRENTRYLISTITEM *copy=nullptr;assert(copyDirList(&copy,state.list));freeDirList(copy);
 failAllocation=true;assert(!copyDirList(&copy,state.list)&&!copy&&errno==ENOMEM);
 FTP_FindClose(&state);FTP_FindClose(&state);assert(!state.list&&!state.next_enum_item);
 errno=0;assert(mystrtoul64("9223372036854775807")==0x7fffffffffffffffULL&&!errno);
 errno=0;assert(mystrtoul64("9223372036854775808")==0&&errno==EOVERFLOW);
}
'''
with tempfile.TemporaryDirectory(prefix='wx-ftp-metadata-') as directory:
    tmp=Path(directory);(tmp/'test.cpp').write_text(code)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-fsanitize=address,undefined',str(tmp/'test.cpp'),'-o',str(tmp/'test')],check=True)
    subprocess.run([str(tmp/'test')],check=True,timeout=10)
print('FTP listing: allocation failure, name/size bounds and repeated cleanup passed')
