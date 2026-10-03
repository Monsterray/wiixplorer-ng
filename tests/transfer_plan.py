#!/usr/bin/env python3
"""Exercise the actual directory transfer planner against oversized/error trees."""
from pathlib import Path
import os,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
def function(source,signature):
 start=source.index(signature);end=source.index('{',start)+1;depth=1
 while depth:
  depth+=(source[end]=='{')-(source[end]=='}');end+=1
 return source[start:end]
src=(ROOT/'source/FileOperations/ProcessTask.cpp').read_text()
harness=r'''
#include <list>
#include <string>
#include <vector>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cassert>
#include <dirent.h>
#include <sys/stat.h>
#include <cerrno>
#include <climits>
using namespace std;using u64=uint64_t;using u32=uint32_t;
#define PROGRESS_CANCELED -10
int mode=0,opened=0,maxOpened=0;bool canceled=false,closing=false;
struct Application{static bool isClosing(){return closing;}};
struct ProgressWindow{static ProgressWindow *Instance(){static ProgressWindow p;return &p;}bool IsCanceled(){return canceled;}};
struct Marker {int count=1;bool directory=true;int GetItemcount(){return count;}bool IsItemDir(int){return directory;}const char *GetItemPath(int){return "sd:/tree";}const char *GetItemName(int){return "tree";}};
struct FakeDir{int index=0;};
DIR *fakeOpen(const char*){++opened;if(opened>maxOpened)maxOpened=opened;return reinterpret_cast<DIR*>(new FakeDir);}
dirent *fakeRead(DIR *dir){static dirent e;auto *d=reinterpret_cast<FakeDir*>(dir);int n=d->index++;memset(&e,0,sizeof(e));
 if(mode==4&&n==1){errno=EIO;return nullptr;}
 if(mode==2){if(n)return nullptr;e.d_type=DT_DIR;strcpy(e.d_name,"d");return &e;}
 if(n>=(mode==1?40000:mode==3?2:1))return nullptr;
 e.d_type=DT_REG;snprintf(e.d_name,sizeof(e.d_name),"file%d",n);return &e;}
int fakeClose(DIR *d){--opened;delete reinterpret_cast<FakeDir*>(d);return mode==5?-1:0;}
int fakeStat(const char *path,struct stat *s){if(mode==3&&strstr(path,"file1")){errno=EIO;return -1;}memset(s,0,sizeof(*s));s->st_mode=mode==2?S_IFDIR:S_IFREG;s->st_size=12;return 0;}
u64 FileSize(const char*){return 12;}
#define opendir fakeOpen
#define readdir fakeRead
#define closedir fakeClose
#define stat(...) fakeStat(__VA_ARGS__)
struct ProcessTask {
 struct ItemList {string basepath;list<string> files,dirs;};
 Marker Process;const string destPath="sd:/destination/";u64 CopySize=0;u32 CopyFiles=0;
 u32 PlanEntries=0,PlanBytes=0;
 static const u32 MaxPlanEntries=32768,MaxPlanBytes=4*1024*1024,MaxPlanDepth=64;
 void ShowProgress(int,u64){}
 bool ReservePlanPath(const string &path);
 int GetItemList(list<ItemList>&,bool);
 int ReadDirectory(string&,ItemList&,bool,unsigned depth=0);
};
'''
if 'bool ProcessTask::ReservePlanPath(' in src:harness+=function(src,'bool ProcessTask::ReservePlanPath(')+'\n'
old='int ProcessTask::ReadDirectory(string &path, ItemList &fileList, bool listDirs)'
if old in src:
 harness+=function(src,'int ProcessTask::GetItemList(')+'\n'
 harness+=function(src,old).replace(old,old[:-1]+', unsigned depth)')+'\n'
else:
 harness+=function(src,'int ProcessTask::GetItemList(')+'\n'+function(src,'int ProcessTask::ReadDirectory(')+'\n'
harness+=r'''
int main(){
 list<ProcessTask::ItemList> list;
 ProcessTask normal;assert(normal.GetItemList(list,true)==0);assert(normal.CopyFiles==1 && normal.CopySize==12 && opened==0);list.clear();
 mode=1;ProcessTask wide;assert(wide.GetItemList(list,true)<0);assert(list.empty() && opened==0);assert(wide.PlanBytes<=wide.MaxPlanBytes);list.clear();
 mode=2;ProcessTask deep;assert(deep.GetItemList(list,true)<0);assert(list.empty() && opened==0 && maxOpened==1);list.clear();
 mode=3;ProcessTask failed;assert(failed.GetItemList(list,true)<0);assert(list.empty() && opened==0);list.clear();
 mode=4;ProcessTask readError;assert(readError.GetItemList(list,true)<0 && list.empty() && opened==0);
 mode=5;ProcessTask closeError;assert(closeError.GetItemList(list,true)<0 && list.empty() && opened==0);
 ProcessTask pathLimit;assert(!pathLimit.ReservePlanPath(string(1024,'x')));
 mode=0;canceled=true;ProcessTask cancel;assert(cancel.GetItemList(list,true)==PROGRESS_CANCELED);assert(list.empty() && opened==0);canceled=false;
 closing=true;ProcessTask exit;assert(exit.GetItemList(list,true)==PROGRESS_CANCELED);assert(list.empty() && opened==0);closing=false;
 ProcessTask selected;selected.Process.count=40000;selected.Process.directory=false;assert(selected.GetItemList(list,true)<0);assert(list.empty());
}
'''
with tempfile.TemporaryDirectory(prefix='wx-plan-test-') as tmp:
 p=Path(tmp);(p/'test.cpp').write_text(harness)
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-fsanitize=address,undefined',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=10)
print('Transfer plan: normal tree, item/path-memory/depth limits, read error, cancellation, exit and closed directory handles passed')
