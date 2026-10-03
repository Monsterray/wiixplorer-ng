#!/usr/bin/env python3
"""Ensure directory transfers preserve empty folders and failed moves' sources."""
from pathlib import Path
import os,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
def function(source,signature):
 start=source.index(signature);end=source.index('{',start)+1;depth=1
 while depth:
  depth+=(source[end]=='{')-(source[end]=='}');end+=1
 return source[start:end]
harness=r'''
#include <list>
#include <string>
#include <cstring>
#include <cstdlib>
#include <cstdio>
#include <cassert>
#include <sys/stat.h>
#include <unistd.h>
using namespace std;
#define PROGRESS_CANCELED -10
bool failCreate=false,closing=false;
struct Application{static bool isClosing(){return closing;}};
struct ProgressWindow {static ProgressWindow *Instance(){static ProgressWindow p;return &p;}bool IsRunning(){return true;}bool IsCanceled(){return false;}void SetTitle(const char*){}void SetCompleteValues(int,int){}};
void StartProgress(const char*){}const char *tr(const char *s){return s;}void ThrowMsg(const char*,const char*){}
struct Marker{int count=1;int GetItemcount(){return count;}const char *GetItemPath(int){return "./src/empty";}bool IsItemDir(int){return true;}void *GetItem(int){return nullptr;}void RemoveItem(void*){--count;}void Reset(){count=0;}};
struct Base {struct ItemList{string basepath;list<string> files,dirs;};Marker Process;string destPath="./dst/";int CopySize=0;
 const string getTitle(){return "transfer";}
 int GetItemList(list<ItemList> &items,bool dirs){ItemList item;item.basepath="./src/";if(dirs)item.dirs={"empty/child","empty"};items.push_back(item);return 0;}
};
struct CopyTask:Base{void Execute();};struct MoveTask:Base{void Execute();};
void TaskBegin(Base*){}void TaskEnd(Base*){}
bool CompareDevices(const char*,const char*){return false;}
bool CheckFile(const char *p){struct stat s;return stat(p,&s)==0;}
int CopyFile(const char*,const char*){assert(false);return -1;}int MoveFile(const char*,const char*){assert(false);return -1;}
bool RemoveFile(const char *p){return remove(p)==0;}
bool CreateSubfolder(const char*);
'''
source=(ROOT/'source/FileOperations/fileops.cpp').read_text()
harness+=function(source,'bool CreateSubfolder(').replace('bool CreateSubfolder(', 'bool realCreateSubfolder(').replace('if(CreateSubfolder(dirpath))', 'if(realCreateSubfolder(dirpath))')+'\n'
harness+='bool CreateSubfolder(const char *p){return !failCreate && realCreateSubfolder(p);}\n'
for name in ('Copy','Move'):
 harness+=function((ROOT/f'source/FileOperations/{name}Task.cpp').read_text(),f'void {name}Task::Execute(')+'\n'
harness+=r'''
void fixture(){mkdir("./src",0700);mkdir("./src/empty",0700);mkdir("./src/empty/child",0700);mkdir("./dst",0700);}
void clean(){rmdir("./src/empty/child");rmdir("./src/empty");rmdir("./dst/empty/child");rmdir("./dst/empty");}
int main(){
 fixture();CopyTask copy;copy.Execute();assert(CheckFile("./dst/empty/child"));assert(CheckFile("./src/empty/child"));clean();
 fixture();MoveTask move;move.Execute();assert(CheckFile("./dst/empty/child"));assert(!CheckFile("./src/empty"));clean();
 fixture();failCreate=true;MoveTask failed;failed.Execute();assert(CheckFile("./src/empty/child"));assert(!CheckFile("./dst/empty"));failCreate=false;clean();
 fixture();closing=true;MoveTask canceledMove;canceledMove.Execute();CopyTask canceledCopy;canceledCopy.Execute();assert(CheckFile("./src/empty/child") && !CheckFile("./dst/empty"));closing=false;clean();
 assert(!CreateSubfolder(string(1024,'x').c_str()));
 string deep="./dst";for(int i=0;i<65;++i)deep+="/d";assert(!CreateSubfolder(deep.c_str()));
 FILE *f=fopen("./dst/file","wb");fclose(f);assert(!CreateSubfolder("./dst/file"));remove("./dst/file");
}
'''
with tempfile.TemporaryDirectory(prefix='wx-empty-transfer-') as tmp:
 p=Path(tmp);(p/'test.cpp').write_text(harness)
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-fsanitize=address,undefined',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],cwd=p,check=True,timeout=10)
print('Directory transfers: empty copy/move, failed destination retains source, existing file is not a directory passed')
