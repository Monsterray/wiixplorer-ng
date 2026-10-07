#!/usr/bin/env python3
"""Production browser batches: lazy empty storage, growth, sort and OOM."""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
def function(signature):
 s=(root/'source/FileOperations/filebrowser.cpp').read_text();a=s.index(signature);b=s.index('{',a);n=1;end=b+1
 while n:n+=(s[end]=='{')-(s[end]=='}');end+=1
 return s[a:end]
code=r'''
#include <cassert>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <climits>
#include <new>
#include <dirent.h>
#include <sys/stat.h>
#include <unistd.h>
#include <cstdio>
#include "Diagnostics/MemoryProbes.h"
#define MAXPATHLEN 512
#define MAXJOLIET 255
#define MAX_PARSE_ITEMS 2
#define FILTER_DIRECTORIES 1
#define FILTER_FILES 2
struct BROWSERENTRY{char *filename;uint64_t length;bool isdir;};
struct {bool HideSystemFiles=false;}Settings;
bool failMalloc=false,failRealloc=false;unsigned errors=0;
void *browserMalloc(size_t n){return failMalloc?nullptr:malloc(n);}void *browserRealloc(void*p,size_t n){return failRealloc?nullptr:realloc(p,n);}
const char *tr(const char *p){return p;}void ThrowMsg(const char*,int,const char*){++errors;}
class FileBrowser {public:
 struct {int numEntries=0;char rootdir[10]=".";char dir[512]="";}browser;
 BROWSERENTRY *browserList=nullptr;DIR *dirIter=nullptr;bool directoryChange=false,bChanged=false;unsigned Filter=0;
 void Lock(){}void Unlock(){}void ResetBrowser();bool ParseDirEntries();
};
#define malloc browserMalloc
#define realloc browserRealloc
'''+function('static void BrowserFreeNames(')+function('void FileBrowser::ResetBrowser()')+function('static int FileSortCallback(')+function('bool FileBrowser::ParseDirEntries()')+r'''
#undef malloc
#undef realloc
int main(){
 BROWSERENTRY null={};assert(FileSortCallback(&null,&null)==0);
 BROWSERENTRY dot={(char*)".",0,true};assert(FileSortCallback(&dot,&dot)==0);
 FileBrowser b;failMalloc=true;b.ResetBrowser();assert(!b.browserList && !b.browser.numEntries);failMalloc=false;
 for(unsigned i=0;i<5;++i){char path[16];snprintf(path,sizeof(path),"file%u",i);FILE *f=fopen(path,"wb");assert(f);fclose(f);}
 b.dirIter=opendir(".");assert(b.dirIter);while(b.ParseDirEntries()){}assert(b.browser.numEntries==6);
 auto original=b.browserList;int count=b.browser.numEntries;
 b.dirIter=opendir(".");failRealloc=true;assert(!b.ParseDirEntries() && b.browserList==original && b.browser.numEntries==count && errors);failRealloc=false;
 b.dirIter=opendir(".");failMalloc=true;assert(!b.ParseDirEntries() && b.browserList==original);failMalloc=false;closedir(b.dirIter);b.dirIter=nullptr;
 b.ResetBrowser();assert(!b.browserList && b.browser.numEntries==0);
 for(unsigned i=0;i<5;++i){char path[16];snprintf(path,sizeof(path),"file%u",i);remove(path);}
}
'''
with tempfile.TemporaryDirectory(prefix='wx-browser-storage-') as t:
 p=Path(t);(p/'test.cpp').write_text(code);work=p/'work';work.mkdir()
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-g','-fsanitize=address,undefined',str(p/'test.cpp'),'-I'+str(root/'source'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],cwd=work,check=True,timeout=10)
print('Browser: empty lists allocate nothing, bounded batch growth, sort equivalence and failed growth retains entries')
