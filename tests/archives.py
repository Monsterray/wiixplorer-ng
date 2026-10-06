#!/usr/bin/env python3
"""ASan/UBSan checks of production archive adapters and bounded parsers.
Codec calls are fault-injectable SDK shims; physical/library checks are separate.
"""
from pathlib import Path
import os, subprocess, tempfile
ROOT=Path(__file__).resolve().parents[1]

def stripped(path):
    return '\n'.join(x for x in (ROOT/path).read_text().splitlines() if not x.startswith('#include'))

common='#include \"'+str(ROOT/'source/Diagnostics/MemoryProbes.h')+'\"\n'+r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <cassert>
#include <climits>
#include <algorithm>
#include <limits>
#include <vector>
#include <set>
#include <memory>
#include <string>
#include <new>
#include <dirent.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <unistd.h>
#include <cerrno>
#include <zlib.h>
using u8=uint8_t;using u16=uint16_t;using u32=uint32_t;using u64=uint64_t;
using namespace std;
bool canceled=false,failWrite=false,failClose=false,failRead=false;
int closeFile(FILE *f){int r=fclose(f);return failClose ? EOF : r;}
size_t writeFile(const void *p,size_t n,size_t count,FILE *f){return failWrite ? 0 : fwrite(p,n,count,f);}
size_t readFile(void *p,size_t n,size_t count,FILE *f){return failRead ? 0 : fread(p,n,count,f);}
#define fclose closeFile
#define fwrite writeFile
#define fread readFile
const int PROGRESS_CANCELED=-10;
struct Application {static bool isClosing(){return false;}};
struct ProgressWindow { static ProgressWindow *Instance(){static ProgressWindow p;return &p;}bool IsCanceled(){return canceled;} };
void ShowProgress(u64,u64,const char* = nullptr){}
void FinishProgress(u64){}
const char *tr(const char *p){return p;}void ThrowMsg(const char*,const char*,...){}
'''
# Minimal minizip interface with short read/CRC/member-close/archive-close faults.
zip_api=r'''
struct Member {string name,data;unsigned attr;};
vector<Member> members,written;
int zipReadMode=0;bool badCrc=false,badMemberClose=false,badArchiveClose=false,badZipWrite=false;
struct Reader {size_t index=0,offset=0;};struct Writer {FILE *file;};
using unzFile=Reader*;using zipFile=Writer*;
const int UNZ_OK=0,ZIP_OK=0,UNZ_END_OF_LIST_OF_FILE=-100;
struct unz_file_info {u64 size_filename,size_file_extra,uncompressed_size,compressed_size,external_fa,dosDate;};
struct unz_global_info {unsigned number_entry;};
struct zip_fileinfo {struct {int tm_sec,tm_min,tm_hour,tm_mday,tm_mon,tm_year;}tmz_date;};
unzFile unzOpen(const char*){return new Reader;}
int unzClose(unzFile r){delete r;return 0;}
int unzGetGlobalInfo(unzFile,unz_global_info *i){i->number_entry=members.size();return 0;}
int unzGoToFirstFile(unzFile r){r->index=0;return members.empty() ? -100 : 0;}
int unzGoToNextFile(unzFile r){return ++r->index<members.size() ? 0 : -100;}
int unzGetCurrentFileInfo(unzFile r,unz_file_info *i,char *name,unsigned capacity,void*,unsigned,void*,unsigned){
 if(r->index>=members.size())return -1;
 auto &m=members[r->index];*i={m.name.size(),0,m.data.size(),m.data.size(),m.attr,0};
 if(name&&capacity){strncpy(name,m.name.c_str(),capacity);if(m.name.size()<capacity)name[m.name.size()]=0;}return 0;
}
int unzOpenCurrentFile(unzFile r){r->offset=0;return 0;}
int unzCloseCurrentFile(unzFile){return badCrc ? -1 : 0;}
int unzReadCurrentFile(unzFile r,void *out,unsigned requested){
 if(zipReadMode==1)return -1;if(zipReadMode==2)return 0;
 auto &data=members[r->index].data;
 size_t size=min<size_t>(requested,data.size()-r->offset);
 if(zipReadMode==3)size=min<size_t>(size,7); // Legitimate short positive codec reads.
 memcpy(out,data.data()+r->offset,size);r->offset+=size;return size;
}
zipFile zipOpen(const char *path,int mode){if(mode==0)written.clear();else written=members;FILE*f=fopen(path,"rb+");return f ? new Writer{f} : nullptr;}
int zipOpenNewFileInZip(zipFile,const char *name,zip_fileinfo*,void*,int,void*,int,void*,int,int){written.push_back({name,"",0});return 0;}
int zipWriteInFileInZip(zipFile,void *p,unsigned n){if(badZipWrite)return -1;written.back().data.append((char*)p,n);return 0;}
int zipCloseFileInZip(zipFile){return badMemberClose ? -1 : 0;}
int zipClose(zipFile f,const char*){int result=closeFile(f->file);delete f;if(badArchiveClose)return -1;members=written;return result;}
'''
# The adapter/allocator uses the real SDK callback signatures and data slice contract.
seven_api=r'''
using Byte=u8;using UInt16=u16;using UInt32=u32;using SRes=int;
const int SZ_OK=0,SZ_ERROR_FAIL=5,SZ_ERROR_MEM=2,SZ_ERROR_DATA=1;const bool False=false;
const Byte k7zSignature[]={55,122,188,175,39,28};
struct ISzAlloc{void*(*Alloc)(void*,size_t);void(*Free)(void*,void*);};
#define IAlloc_Free(p,a) (p)->Free(p,a)
struct CSzFile{FILE *file;};struct CFileInStream{int s;CSzFile file;};struct CLookToRead{int s;int *realStream;};
struct CSzFileItem{struct {u32 Low,High;}MTime;u64 Size;u32 Attrib=0;bool IsDir=false,IsAnti=false,AttribDefined=false,MTimeDefined=false;};
struct CSzArEx{struct {unsigned NumFiles;CSzFileItem *Files;}db;void *allocation;};
vector<string> sevenNames;vector<CSzFileItem> sevenItems;string decodedData;size_t decodedOffset=13,allocationRequest=0;bool sevenCorrupt=false;
void File_Construct(CSzFile*p){p->file=nullptr;}int InFile_Open(CSzFile*p,const char*path){p->file=fopen(path,"rb");return !p->file;}
int File_Close(CSzFile*p){if(!p->file)return 0;return closeFile(p->file);}
void SzArEx_Init(CSzArEx*p){memset(p,0,sizeof(*p));}void FileInStream_CreateVTable(CFileInStream*){}void LookToRead_CreateVTable(CLookToRead*,bool){}void LookToRead_Init(CLookToRead*){}void CrcGenerateTable(){}
SRes SzArEx_Open(CSzArEx*p,int*,ISzAlloc*a,ISzAlloc*){p->allocation=nullptr;if(allocationRequest){p->allocation=a->Alloc(a,allocationRequest);if(!p->allocation)return SZ_ERROR_MEM;}p->db={unsigned(sevenItems.size()),sevenItems.data()};return 0;}
void SzArEx_Free(CSzArEx*p,ISzAlloc*a){a->Free(a,p->allocation);}
size_t SzArEx_GetFileNameUtf16(CSzArEx*,size_t i,UInt16*out){if(out){for(size_t n=0;n<sevenNames[i].size();++n)out[n]=sevenNames[i][n];out[sevenNames[i].size()]=0;}return sevenNames[i].size()+1;}
SRes SzArEx_Extract(CSzArEx*,int*,unsigned,UInt32 *index,Byte **out,size_t *capacity,size_t *offset,size_t *size,ISzAlloc*a,ISzAlloc*){
 if(sevenCorrupt)return 3;
 a->Free(a,*out);*capacity=decodedOffset+decodedData.size();*out=(Byte*)a->Alloc(a,*capacity);if(!*out)return SZ_ERROR_MEM;
 memset(*out,0xdd,*capacity);memcpy(*out+decodedOffset,decodedData.data(),decodedData.size());*offset=decodedOffset;*size=decodedData.size();*index=0;return 0;
}
class wString {string value;public:void push_back(UInt16 c){value+=(char)c;}string toUTF8(){return value;}};
'''

# Exercise RAR's production index guard and virtual bounded writer separately
# from the third-party decoder, which has no mid-unpack callback guarantee.
rar_source=(ROOT/'source/ArchiveOperations/RarFile.cpp').read_text()
rar_bounds=rar_source[rar_source.index('ArchiveFileStruct * RarFile::GetFileStruct'):rar_source.index('u32 RarFile::GetItemCount')]
rar_io=rar_source[rar_source.index('class RarFileDataIO'):rar_source.index('void RarFile::UnstoreFile')]
rar_api=r'''
struct Archive {struct {u64 FullPackSize=10;}NewLhd;};
struct ComprDataIO {long long CurUnpRead=0,CurUnpWrite=0;virtual ~ComprDataIO(){}virtual int UnpRead(u8*,size_t n){CurUnpRead+=n;return n;}virtual void UnpWrite(u8*,size_t n){CurUnpWrite+=n;}};
using byte=u8;
struct RarFile {bool ListValid=true;vector<ArchiveFileStruct*>RarStructure;ArchiveFileStruct *GetFileStruct(int);};
'''

helpers=r'''
void put(const string &path,const string &data){FILE *f=fopen(path.c_str(),"wb");assert(f);assert(::writeFile(data.data(),1,data.size(),f)==data.size());assert(::closeFile(f)==0);}
string get(const string &path){FILE *f=fopen(path.c_str(),"rb");assert(f);string s;char b[4096];size_t n;while((n=::readFile(b,1,sizeof(b),f)))s.append(b,n);assert(::closeFile(f)==0);return s;}
bool exists(const char*p){struct stat st;return lstat(p,&st)==0;}
void be32(vector<u8>&v,size_t off,u32 n){for(unsigned i=0;i<4;++i)v[off+i]=n>>(24-i*8);}
void be16(vector<u8>&v,size_t off,u16 n){v[off]=n>>8;v[off+1]=n;}
vector<u8> u8archive(){
 vector<u8>v(128);be32(v,0,0x55aa382d);be32(v,4,32);be32(v,8,43);be32(v,12,96);
 be32(v,32,0x01000000);be32(v,40,3);be32(v,44,0x01000001);be32(v,48,0);be32(v,52,3);
 be32(v,56,3);be32(v,60,96);be32(v,64,3);memcpy(v.data()+68,"\0d\0f\0",5);memcpy(v.data()+96,"abc",3);return v;
}
vector<u8> rarc(){
 vector<u8>v(132);memcpy(v.data(),"RARC",4);be32(v,4,v.size());be32(v,12,96);be32(v,32,1);be32(v,36,32);
 be32(v,40,1);be32(v,44,48);be32(v,48,8);be32(v,52,68);
 memcpy(v.data()+64,"ROOT",4);be32(v,68,0);be16(v,74,1);be32(v,76,0);
 be16(v,80,0);be16(v,84,0x100);be16(v,86,5);be32(v,88,0);be32(v,92,3);memcpy(v.data()+100,"root\0f\0",7);memcpy(v.data()+128,"abc",3);return v;
}
struct InspectArchive:WiiArchive {InspectArchive(const u8*p,u32 n):WiiArchive(p,n){}using WiiArchive::ReadFile;};
'''
main=r'''
int main(){
 mkdir("out",0700);mkdir("outside",0700);put("dummy","x");char path[768];
 for(const char *name:{"../x","a/../../x","/x","sd:/x","a\\..\\x","a\nx","a//x",".",""})assert(!wx_archive_path(path,sizeof(path),"out",name,true));
 assert(!wx_archive_member(string(768,'a').c_str()));string deep="f";for(int i=0;i<32;++i)deep+="/f";assert(!wx_archive_member(deep.c_str()));
 assert(wx_archive_path(path,sizeof(path),"sd:/out","a/b",true)&&!strcmp(path,"sd:/out/a/b"));
 assert(wx_archive_path(path,sizeof(path),"out/","a/b",false)&&!strcmp(path,"out/b"));
 assert(!wx_archive_path(path,4,"out","file",true));
 symlink("../outside","out/link");ArchiveOutput linked;assert(!linked.Begin("out","link/file",true));
 put("outside/original","safe");symlink("../outside/original","out/symlink");ArchiveOutput linkFile;assert(!linkFile.Begin("out","symlink",false));
 put("out/file","original");{ArchiveOutput f;assert(f.Begin("out","file",true));assert(writeFile("new",1,3,f.file)==3);}assert(get("out/file")=="original");
 {ArchiveOutput f;assert(f.Begin("out","file",true));assert(writeFile("new",1,3,f.file)==3);failClose=true;assert(!f.Commit());failClose=false;}assert(get("out/file")=="original");
 {ArchiveOutput f;assert(f.Begin("out","file",true));assert(writeFile("new",1,3,f.file)==3);assert(f.Commit());}assert(get("out/file")=="new");
 assert(!wx_archive_space("out",UINT64_MAX));
 members={{"file",string(100001,'q'),0},{"empty/","",0},{"emptyfile","",0},{"small","ab",0},{"large",string(150000,'l'),0},{"synthetic/nested","n",0}};
 {ZipFile z("dummy");assert(z.GetItemCount()==7);assert(!z.GetFileStruct(-1)&&!z.GetFileStruct(7));zipReadMode=3;assert(z.ExtractAll("out")==1);zipReadMode=0;assert(get("out/file")==members[0].data&&get("out/large")==members[4].data);assert(exists("out/empty")&&get("out/emptyfile").empty());assert(z.ExtractFile(6,"out",true)==1);}
 {ZipFile z("dummy");ArchiveBrowser b(&z);b.ParseArchiveDirectory("");bool found=false;for(unsigned i=0;i<b.PathStructure.size();++i)if(!strcmp(b.PathStructure[i]->filename,"synthetic")){assert(b.ExtractItem(i,"out")==1);found=true;}assert(found&&get("out/synthetic/nested")=="n");}
 for(int failure=0;failure<6;++failure){put("out/file","original");ZipFile z("dummy");if(failure==0)zipReadMode=1;if(failure==1)zipReadMode=2;if(failure==2)badCrc=true;if(failure==3)failWrite=true;if(failure==4)failClose=true;if(failure==5)canceled=true;assert(z.ExtractFile(0,"out",true)<0);zipReadMode=0;badCrc=failWrite=failClose=canceled=false;assert(get("out/file")=="original");}
 for(const char *unsafe:{"../x","sd:/x","/x","a\\b"}){members={{unsafe,"x",0}};ZipFile z("dummy");assert(z.GetItemCount()==0&&z.ExtractAll("out")<0);}
 members={{"link","x",0120000u<<16}};{ZipFile z("dummy");assert(z.GetItemCount()==0);}
 mkdir("tree",0700);mkdir("tree/sub",0700);mkdir("tree/empty",0700);put("tree/a","aaa");put("tree/sub/b","bbb");
 {ZipFile z("new.zip",ZipFile::CREATE);assert(z.AddDirectory("tree","top",6)==1);set<string> names;for(auto&m:written)assert(names.insert(m.name).second);assert(names==set<string>({"top/","top/a","top/sub/","top/sub/b","top/empty/"}));}
 put("archive.zip","original");
 {ZipFile z("archive.zip",ZipFile::CREATE);assert(z.AddFile("tree/a",NULL,6)<0);assert(get("archive.zip")=="original");}
 for(int failure=0;failure<6;++failure){ZipFile z("archive.zip",ZipFile::CREATE);if(failure==0)badZipWrite=true;if(failure==1)badMemberClose=true;if(failure==2)badArchiveClose=true;if(failure==3)failRead=true;if(failure==4)canceled=true;assert(z.AddDirectory("tree","top",failure==5 ? 10 : 6)<0);badZipWrite=badMemberClose=badArchiveClose=failRead=canceled=false;assert(get("archive.zip")=="original");}
 string branch="tree";for(unsigned i=0;i<33;++i){branch+="/d";mkdir(branch.c_str(),0700);} {ZipFile z("archive.zip",ZipFile::CREATE);assert(z.AddDirectory("tree","top",6)<0);assert(get("archive.zip")=="original");}
 sevenNames={"seven"};sevenItems.resize(1);sevenItems[0].Size=5;decodedData="hello";
 {SzFile s("dummy");assert(!s.GetFileStruct(1)&&!s.GetFileStruct(-1));assert(s.ExtractFile(0,"out",true)==1);assert(get("out/seven")=="hello");}
 decodedData=string(180000,'s');sevenItems[0].Size=decodedData.size();{SzFile s("dummy");assert(s.ExtractAll("out")==1);assert(get("out/seven")==decodedData);}
 for(int f=0;f<4;++f){put("out/seven","original");SzFile s("dummy");if(f==0)sevenCorrupt=true;if(f==1)failWrite=true;if(f==2)failClose=true;if(f==3)canceled=true;assert(s.ExtractFile(0,"out",true)<0);sevenCorrupt=failWrite=failClose=canceled=false;assert(get("out/seven")=="original");}
 allocationRequest=WX_ARCHIVE_METADATA+1;{SzFile s("dummy");assert(s.GetItemCount()==0);}allocationRequest=0;
 decodedData=string(17*1024*1024,'x');sevenItems[0].Size=decodedData.size();{SzFile s("dummy");assert(s.ExtractFile(0,"out",true)<0);}
 sevenItems[0].Size=UINT64_C(0x100000001);{SzFile s("dummy");assert(s.GetFileStruct(0)->length==UINT64_C(0x100000001));assert(s.ExtractFile(0,"out",true)<0);} // SDK mismatch cannot truncate into success.
 const u8 lz[]={'L','Z','7','7',0x10,6,0,0,0x40,'A',0x20,0};u32 size;u8 *data=uncompressLZ77(lz,sizeof(lz),&size);assert(data&&size==6&&!memcmp(data,"AAAAAA",6));free(data);
 for(unsigned n=0;n<sizeof(lz);++n)assert(!uncompressLZ77(lz,n,&size));
 u8 bad[sizeof(lz)];memcpy(bad,lz,sizeof(lz));bad[8]=0x80;assert(!uncompressLZ77(bad,sizeof(bad),&size));
 const u8 yaz[]={'Y','a','z','0',0,0,0,6,0,0,0,0,0,0,0,0,0x80,'A',0x30,0};u8 output[6];assert(uncompressYaz0(yaz,sizeof(yaz),output,6)&&!memcmp(output,"AAAAAA",6));
 for(unsigned n=0;n<sizeof(yaz);++n)assert(!uncompressYaz0(yaz,n,output,6));memcpy(bad,lz,sizeof(lz));assert(!uncompressYaz0(yaz,sizeof(yaz),output,5));
 vector<u8> invalidYaz(yaz,yaz+sizeof(yaz));invalidYaz[16]=0;assert(!uncompressYaz0(invalidYaz.data(),invalidYaz.size(),output,6));
 invalidYaz.assign(yaz,yaz+sizeof(yaz));invalidYaz[18]=0;assert(!uncompressYaz0(invalidYaz.data(),invalidYaz.size(),output,6)); // Missing extended run byte.
 invalidYaz.push_back(0);assert(!uncompressYaz0(invalidYaz.data(),invalidYaz.size(),output,6)); // Run exceeds declared output.
 memcpy(bad,lz,sizeof(lz));bad[10]=0xf0;assert(!uncompressLZ77(bad,sizeof(bad),&size)&&size==0);
 auto u=u8archive();{U8Archive a(u.data(),u.size());assert(a.GetItemCount()==2&&a.ExtractAll("out")==1&&!a.GetFileStruct(2));assert(get("out/d/f")=="abc");}
 {InspectArchive a(u.data(),u.size());u8 byte;assert(a.ReadFile(&byte,1,UINT64_MAX)==0&&a.ReadFile(&byte,2,u.size()-1)==0);}
 for(size_t pos:{4u,8u,12u,40u,56u,60u}){auto v=u;be32(v,pos,UINT32_MAX);U8Archive a(v.data(),v.size());assert(a.GetItemCount()==0&&a.ExtractAll("out")<0);}
 for(unsigned n=0;n<99;++n){U8Archive a(u.data(),n);assert(a.GetItemCount()==0);}
 auto r=rarc();{RarcFile a(r.data(),r.size());assert(a.GetItemCount()==2&&a.ExtractAll("out")==1&&!a.GetFileStruct(2));assert(get("out/root/f")=="abc");}
 for(size_t pos:{4u,12u,32u,36u,40u,44u,48u,52u,76u,88u,92u}){auto v=r;be32(v,pos,UINT32_MAX);RarcFile a(v.data(),v.size());assert(a.GetItemCount()==0&&a.ExtractAll("out")<0);}
 auto cycle=r;be16(cycle,80,0xffff);be32(cycle,88,0);{RarcFile a(cycle.data(),cycle.size());assert(a.GetItemCount()==0);}
 for(unsigned n=0;n<131;++n){RarcFile a(r.data(),n);assert(a.GetItemCount()==0);}
 ArchiveFileStruct large={};large.length=UINT64_C(0x100000001);large.comp_length=UINT64_C(0x200000002);
 {RarFile a;a.RarStructure.push_back(&large);assert(!a.GetFileStruct(1)&&!a.GetFileStruct(-1));assert(a.GetFileStruct(0)->length==UINT64_C(0x100000001)&&a.GetFileStruct(0)->comp_length==UINT64_C(0x200000002));}
 put("out/rarfile","original");
 for(int fault=0;fault<3;++fault){ArchiveOutput o;assert(o.Begin("out","rarfile",true));Archive arc;RarFileDataIO io(&arc,o.file,3);u8 bytes[4]={1,2,3,4};if(fault==0)failWrite=true;if(fault==1)canceled=true;io.UnpWrite(bytes,fault==2 ? 4 : 3);assert(io.failed&&io.CurUnpWrite==0);failWrite=canceled=false;}assert(get("out/rarfile")=="original");
 for(int fault=0;fault<3;++fault){put("out/d/f","original");U8Archive a(u.data(),u.size());if(fault==0)failWrite=true;if(fault==1)failClose=true;if(fault==2)canceled=true;assert(a.ExtractFile(1,"out",true)<0);failWrite=failClose=canceled=false;assert(get("out/d/f")=="original");}
 static_assert(sizeof(ArchiveFileStruct::length)==8,"archive sizes must remain 64 bit");
}
'''

browser_api=r'''
struct ArchiveBrowser {
 ZipFile *archive;vector<ArchiveFileStruct*> PathStructure;unsigned ItemNumber;int PageIndex=0,SelIndex=0;
 ArchiveBrowser(ZipFile *a):archive(a),ItemNumber(a->GetItemCount()){}~ArchiveBrowser(){ClearList();}
 void ClearList(){for(auto*p:PathStructure){delete[]p->filename;delete p;}PathStructure.clear();}
 void AddListEntrie(const char*n,u64 a,u64 b,bool d,u32 i,u64 t,u8 type){auto*p=new ArchiveFileStruct();p->filename=new char[strlen(n)+1];strcpy(p->filename,n);p->length=a;p->comp_length=b;p->isdir=d;p->fileindex=i;PathStructure.push_back(p);}
 bool InDirectoryTree(const char*,const char*,bool){return true;}void SortList(){reverse(PathStructure.begin(),PathStructure.end());}
 int ParseArchiveDirectory(const char*);int ExtractItem(int,const char*);int ExtractFolder(const char*,const char*);
};
'''
browser_source=(ROOT/'source/ArchiveOperations/ArchiveBrowser.cpp').read_text()
browser_methods=browser_source[browser_source.index('int ArchiveBrowser::ExtractItem('):browser_source.index('int ArchiveBrowser::ExtractAll(')]
browser_methods+=browser_source[browser_source.index('int ArchiveBrowser::ParseArchiveDirectory('):browser_source.index('void ArchiveBrowser::ClearList(')]

def run():
    with tempfile.TemporaryDirectory(prefix='wx-archives-') as tmp:
        p=Path(tmp)
        # Headers are production class declarations, with only SDK includes substituted.
        code=common+stripped('source/ArchiveOperations/ArchiveStruct.h')
        code+='\n#include "ArchiveOperations/ArchiveSafety.h"\n'+stripped('source/ArchiveOperations/ArchiveSafety.cpp')
        code+=zip_api+stripped('source/ArchiveOperations/ZipFile.h')+stripped('source/ArchiveOperations/ZipFile.cpp')
        code+=browser_api+browser_methods
        code+=seven_api+stripped('source/ArchiveOperations/7ZipFile.h')+stripped('source/ArchiveOperations/7ZipFile.cpp')
        code+=stripped('source/Tools/uncompress.h')+stripped('source/Tools/uncompress.c')
        for name in ('WiiArchive','U8Archive','RarcFile'):
            code+=stripped('source/ArchiveOperations/'+name+'.h')+stripped('source/ArchiveOperations/'+name+'.cpp')
        code+=rar_api+rar_bounds+rar_io+helpers+main
        (p/'test.cpp').write_text(code)
        subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-O1','-g','-fsanitize=address,undefined','-I'+str(ROOT/'source'),str(p/'test.cpp'),'-lz','-o',str(p/'test')],check=True)
        subprocess.run([str(p/'test')],cwd=p,check=True,timeout=60)
    print('Archives: production confinement/staging, ZIP trees and I/O faults, 7z slices/budget/bounds, LZ/Yaz0 overlaps, U8/RARC corrupt metadata passed')

if __name__=="__main__":
    run()
