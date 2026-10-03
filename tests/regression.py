#!/usr/bin/env python3
"""Compile the real transfer/GPT functions with small host platform stubs."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def function(path, signature):
    source = (ROOT / path).read_text()
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


transfer = '#include \"' + str(ROOT / 'source/Diagnostics/Probes.h') + '\"\n' + r'''
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <sys/stat.h>
#include <unistd.h>
using u8 = uint8_t; using u32 = uint32_t; using u64 = uint64_t;
const int BLOCKSIZE = 16, PROGRESS_CANCELED = -10;
bool replaceall = false, replacenone = false, canceled = false;
bool sameDevice = false, failClose = false;
int choice = 2;
struct Application { static bool isClosing() { return canceled; } };
struct ProgressWindow {
 static ProgressWindow *Instance() { static ProgressWindow p; return &p; }
 bool IsCanceled() { return canceled; }
};
int GetReplaceChoice(const char *) { return choice; }
void ShowProgress(u64, u64, const char *) {}
void FinishProgress(u64) {}
u64 FileSize(const char *p) { struct stat st; return stat(p, &st) ? 0 : st.st_size; }
bool CheckFile(const char *p) { return access(p, F_OK) == 0; }
bool CompareDevices(const char *, const char *) { return sameDevice; }
bool RemoveFile(const char *p) { return remove(p) == 0; }
bool RenameFile(const char *s, const char *d) { return rename(s, d) == 0; }
void *memalign(size_t, size_t n) { return malloc(n); }
int closeFile(FILE *f) { int result = fclose(f); return failClose ? EOF : result; }
#define fclose closeFile
'''
transfer += '#include \"' + str(ROOT / 'source/FileOperations/TransferFile.h') + '\"\n'
transfer += '\nint CopyFile(const char*, const char*, u32 bufferSize = BLOCKSIZE);\n'
transfer += function('source/FileOperations/fileops.cpp', 'int CopyFile(')
transfer += function('source/FileOperations/fileops.cpp', 'int MoveFile(')
transfer += r'''
#undef fclose
void put(const char *p, const char *s) {
 FILE *f = fopen(p, "wb"); assert(f); fputs(s, f); assert(fclose(f) == 0);
}
void expect(const char *p, const char *s) {
 char b[100] = {}; FILE *f = fopen(p, "rb"); assert(f);
 fread(b, 1, sizeof(b)-1, f); fclose(f); assert(strcmp(b, s) == 0);
}
int main() {
 const char *src = "./src", *dst = "./dst";
 put(src, "source"); put(dst, "existing");
 assert(MoveFile(src, dst) == 0); expect(src, "source"); expect(dst, "existing");
 replacenone = true; assert(MoveFile(src, dst) == 0); expect(src, "source");
 replacenone = false; sameDevice = true;
 assert(MoveFile(src, dst) == 0); expect(src, "source");
 sameDevice = false; choice = 1;
 assert(MoveFile(src, dst) == 1); assert(!CheckFile(src)); expect(dst, "source");
 put(src, "keep on error");
 assert(MoveFile(src, "./missing/dst") < 0); expect(src, "keep on error");
 failClose = true;
 assert(MoveFile(src, dst) < 0); expect(src, "keep on error"); expect(dst, "source");
 failClose = false; canceled = true;
 assert(MoveFile(src, dst) == PROGRESS_CANCELED); expect(src, "keep on error");
 canceled = false; assert(CopyFile(src, src) < 0); expect(src, "keep on error");
 sameDevice = true; assert(MoveFile("./absent", dst) < 0); expect(dst, "source");
 sameDevice = false; put(src, "");
 assert(MoveFile(src, dst) == 1); assert(!CheckFile(src)); expect(dst, "");
}
'''

smoke = r'''
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <cctype>
#include <initializer_list>
using u32=uint32_t;
''' + function('source/main.cpp', 'static u32 ParseSmokeFrames(') + r'''
int main(){
 assert(ParseSmokeFrames("600")==600);assert(ParseSmokeFrames("36000\r\n")==36000);
 for(const char *s : {"", "0", "-1", "36001", "1garbage", "9999999999999999999999999"}) assert(ParseSmokeFrames(s)==0);
 assert(ParseSmokeFrames(nullptr)==0);
}
'''

heap = r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
struct LockMutex { explicit LockMutex(int&){} };
struct CMEM2Alloc {
 struct alignas(32) SBlock { unsigned s; SBlock *next,*prev; bool f; };
 SBlock *m_baseAddress,*m_endAddress,*m_first; int m_mutex;
 bool CheckIntegrity();
};
''' + function('source/Memory/mem2alloc.cpp', 'bool CMEM2Alloc::CheckIntegrity()') + r'''
int main(){
 CMEM2Alloc::SBlock blocks[8]={};
 CMEM2Alloc a={blocks,blocks+8,blocks,0};
 blocks[0].s=1;blocks[0].next=blocks+2;blocks[2].s=5;blocks[2].prev=blocks;
 assert(a.CheckIntegrity());
 blocks[2].prev=nullptr;assert(!a.CheckIntegrity());blocks[2].prev=blocks;
 blocks[2].next=blocks;assert(!a.CheckIntegrity());blocks[2].next=nullptr;
 blocks[2].s=UINT32_MAX;assert(!a.CheckIntegrity());blocks[2].s=5;
 blocks[0].next=reinterpret_cast<CMEM2Alloc::SBlock*>(uintptr_t(1));assert(!a.CheckIntegrity());
 a.m_first=nullptr;assert(a.CheckIntegrity());
}
'''

exit_code = r'''
#include <cassert>
static bool cleanupComplete=false;
enum ExitAction { ExitLoader, ExitMenu, ExitHBC, ExitReboot, ExitPower, ExitIdle, ExitStandby };
static ExitAction exitAction=ExitLoader;
int closed=0, cleaned=0, performed=-1;
struct Application { static void closeRequest(){++closed;} };
extern "C" void Sys_ExecuteExit();
void ExitApp(){if(!cleanupComplete){++cleaned;cleanupComplete=true;}}
void PerformLoader(){performed=0;} void PerformMenu(){performed=1;} void PerformHBC(){performed=2;}
void PerformReboot(){performed=3;} void PerformShutdown(){performed=4;} void PerformIdle(){performed=5;}
void PerformStandby(){performed=6;}
'''
exit_code += function('source/sys.cpp', 'static void RequestExit(')
for signature in ['extern "C" void Sys_Reboot(', 'extern "C" void Sys_Shutdown(',
                  'extern "C" void Sys_ShutdownToIdle(', 'extern "C" void Sys_ShutdownToStandby(',
                  'extern "C" void Sys_LoadMenu(', 'extern "C" void Sys_BackToLoader(',
                  'extern "C" void Sys_LoadHBC(', 'extern "C" void Sys_ExecuteExit(']:
    exit_code += function('source/sys.cpp', signature)
exit_code += r'''
int main(){
 void (*actions[])()={Sys_BackToLoader,Sys_LoadMenu,Sys_LoadHBC,Sys_Reboot,Sys_Shutdown,Sys_ShutdownToIdle,Sys_ShutdownToStandby};
 for(int i=0;i<7;++i){
  cleanupComplete=false;closed=cleaned=0;performed=-1;
  actions[i]();assert(closed==1);assert(cleaned==0);assert(performed==-1);
  Sys_ExecuteExit();assert(cleaned==1);assert(performed==i);
  // A homebrew booter may request return after it has already run cleanup.
  actions[i]();assert(cleaned==1);assert(closed==1);assert(performed==i);
 }
}
'''

partition_header = (ROOT / 'source/DeviceControls/PartitionHandle.h').read_text()
partition = r'''
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <vector>
using u8=uint8_t; using u16=uint16_t; using u32=uint32_t; using u64=uint64_t;
const int MAX_SECTOR_SIZE=4096, MBR_SIGNATURE=0xAA55, PARTITION_TYPE_GPT=0xee;
const int PARTITION_TYPE_DOS33_EXTENDED=5, PARTITION_TYPE_WIN95_EXTENDED=15, PARTITION_BOOTABLE=0x80;
u32 le32(u32 x){return x;}
const char *PartFromType(int){return "FAT";}
''' + partition_header[partition_header.index('typedef struct _PARTITION_RECORD'):partition_header.index('typedef struct _GPT_HEADER')] + r'''
u8 sector[512];
struct Interface { bool readSectors(u64,int,void *p){memcpy(p,sector,512);return true;} } device;
struct PartitionHandle {
 Interface *interface=&device; u32 sectorSize=512;
 std::vector<u64> starts,sizes;
 void AddPartition(const char*,u64 lba,u64 size,bool,int,int){starts.push_back(lba);sizes.push_back(size);}
 int CheckGPT(int){return -1;} void CheckEBR(int,u32){}
 int FindPartitions();
};
''' + function('source/DeviceControls/PartitionHandle.cpp', 'int PartitionHandle::FindPartitions()') + r'''
void setup(int offset){
 memset(sector,0,sizeof(sector)); sector[510]=0x55;sector[511]=0xaa;
 sector[11]=0;sector[12]=2;sector[13]=8;sector[14]=32;sector[16]=2;
 sector[32]=0;sector[33]=0x10;memcpy(sector+offset,"FAT",3);
}
int main(){
 for(int offset : {0x36,0x52}){
  setup(offset);PartitionHandle p;assert(p.FindPartitions()==0);
  assert(p.starts.size()==1);assert(p.starts[0]==0);assert(p.sizes[0]==4096);
 }
 setup(0x52);sector[13]=0;PartitionHandle bad;bad.FindPartitions();assert(bad.starts.empty());
 memset(sector,0,sizeof(sector));sector[510]=0x55;sector[511]=0xaa;
 auto *mbr=reinterpret_cast<MASTER_BOOT_RECORD*>(sector);
 mbr->partitions[0].type=0x0c;mbr->partitions[0].lba_start=2048;mbr->partitions[0].block_count=8192;
 PartitionHandle normal;assert(normal.FindPartitions()==0);assert(normal.starts[0]==2048);assert(normal.sizes[0]==8192);
}
'''

header = (ROOT / 'source/DeviceControls/PartitionHandle.h').read_text()
structures = header[header.index('typedef struct _GPT_HEADER'):header.index('typedef struct _PartitionFS')]
gpt = r'''
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <vector>
using u8 = uint8_t; using u32 = uint32_t; using u64 = uint64_t;
const int MAX_SECTOR_SIZE = 4096, PARTITION_TYPE_GPT = 0xee;
u32 le32(u32 x) { return x; } u64 le64(u64 x) { return x; }
const char TYPE_UNUSED[16] = {}, TYPE_BIOS[16] = {2};
''' + structures + r'''
std::vector<std::vector<u8>> disk;
struct Interface {
 bool readSectors(u64 lba, int, void *p) {
  if(lba >= disk.size()) return false;
  memcpy(p, disk[lba].data(), disk[lba].size()); return true;
 }
} device;
struct PartitionHandle {
 Interface *interface = &device; u32 sectorSize = 512;
 std::vector<u64> starts, sizes;
 void AddPartition(const char *, u64 start, u64 size, bool, int, int) {
  starts.push_back(start); sizes.push_back(size);
 }
 int CheckGPT(int);
};
'''
gpt += function('source/DeviceControls/PartitionHandle.cpp', 'int PartitionHandle::CheckGPT(')
gpt += r'''
void setup(u32 count, u32 entrySize = 128) {
 disk.assign(4, std::vector<u8>(512));
 GPT_HEADER h = {}; memcpy(h.magic, "EFI PART", 8);
 h.part_table_lba = 2; h.part_entries = count; h.part_entry_size = entrySize;
 memcpy(disk[1].data(), &h, 512);
 for(int i = 0; i < 8; ++i) {
  GUID_PART_ENTRY e = {}; e.part_type_guid[0] = 1;
  e.part_first_lba = 100 + i*10; e.part_last_lba = e.part_first_lba + 4;
  memcpy(disk[2+i/4].data()+(i%4)*128, &e, sizeof(e));
 }
}
int main() {
 setup(6); PartitionHandle p; assert(p.CheckGPT(0) == 0);
 assert(p.starts.size() == 6); assert(p.starts.back() == 150);
 for(auto size : p.sizes) assert(size == 5);
 setup(0); PartitionHandle empty; assert(empty.CheckGPT(0) == 0); assert(empty.starts.empty());
 for(u32 size : {0u, 64u, 129u, 8192u}) {
  setup(6, size); PartitionHandle bad; assert(bad.CheckGPT(0) == -1);
 }
 setup(6); memset(disk[2].data(), 0, 128);
 PartitionHandle unused; assert(unused.CheckGPT(0) == 0); assert(unused.starts.size() == 5);
 setup(6); auto *e = reinterpret_cast<GUID_PART_ENTRY *>(disk[2].data());
 e->part_last_lba = 99; PartitionHandle reversed;
 assert(reversed.CheckGPT(0) == 0); assert(reversed.starts.size() == 5);
}
'''

http = '#include \"' + str(ROOT / 'source/Diagnostics/Probes.h') + '\"\n' + r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
typedef uint8_t u8; typedef uint64_t u64; typedef uint32_t u32; typedef int32_t s32;
#include <ctype.h>
u64 wx_transfer_deadline(u32 s) { return s; }
int wx_transfer_expired(u64 d) { (void)d; return 0; }
struct http_reader { int connection; u8 pending[4096]; u32 offset, count; u64 deadline; };
struct block { u32 size; unsigned char *data; };
const struct block emptyblock = {0, NULL};
#define NET_BUFFER_SIZE 1024
#define HTTP_BUFFER_SIZE 5120
#define HTTP_BUFFER_GROWTH 5120
char sent[100] = {0}; size_t sentSize = 0;
const char *reply; size_t position; int readError;
int usleep(unsigned int n) { (void)n; return 0; }
int net_write(int fd, const void *p, int n) {
 (void)fd; if(n > 3) n = 3;
 memcpy(sent+sentSize, p, n); sentSize += n; return n;
}
int net_send(int fd, const void *p, int n, int flags) {
 (void)fd; (void)p; (void)flags; return n;
}
int net_read(int fd, void *p, int n) {
 (void)fd; if(readError) return -1;
 int left = strlen(reply)-position; if(n > left) n = left;
 memcpy(p, reply+position, n); position += n; return n;
}
int net_recv(int fd, void *p, int n, int flags) {
 (void)flags; return net_read(fd, p, n);
}
'''
http += '\n#define wx_transfer_write net_write\n#define wx_transfer_read net_read\n'
for signature in ['static s32 send_message(', 'struct block read_message(', 'int network_request(', 'int http_read(']:
    http += function('source/network/http.c', signature)
http += r'''
int main(void) {
 struct http_reader reader;
 char message[] = "abcdefghij";
 assert(send_message(0, message) == 0); assert(strcmp(sent, message) == 0);
 reply = ""; struct block b = read_message(0); assert(!b.data && !b.size);
 reply = "hello"; position = 0; b = read_message(0);
 assert(b.size == 5 && memcmp(b.data, "hello", 5) == 0); free(b.data);
 readError = 1; b = read_message(0); assert(!b.data); readError = 0;
 reply = "HTTP/1.1 200 OK\r\nContent-Length: 12\r\n\r\n"; position = 0;
 assert(network_request(&reader, 0, "GET", NULL) == 12);
 reply = "HTTP/1.1 200 OK\r\nContent-Length: broken\r\n\r\n"; position = 0;
 assert(network_request(&reader, 0, "GET", NULL) == -1);
 reply = "HTTP/1.1 200 OK\r\nContent-Length: 4294967295\r\n\r\n"; position = 0;
 assert(network_request(&reader, 0, "GET", NULL) == -1);
 reply = "HTTP/1.0 200 OK\r\ncontent-length: 5\r\n\r\nhello"; position = 0;
 assert(network_request(&reader, 0, "GET", NULL) == 5);
 u8 body[5]; assert(http_read(&reader, body, 5) == 5 && !memcmp(body,"hello",5));
 reply = "HTTP/1.1 200 OK\r\nContent-Length: 5\r\nContent-Length: 6\r\n\r\n"; position = 0;
 assert(network_request(&reader, 0, "GET", NULL) == -1);
 reply = "HTTP/1.1 200 OK\r\nContent-Length: 1\r\nContent-Disposition: filename=\"../lost\"\r\n\r\n"; position=0;
 char filename[255]; assert(network_request(&reader,0,"GET",filename)==-1);
 char longReply[5000]; memset(longReply, 'a', sizeof(longReply)-1);
 longReply[sizeof(longReply)-1] = 0; reply = longReply; position = 0;
 assert(network_request(&reader, 0, "GET", NULL) == -1);
}
'''

devoptab = r'''
#include <cassert>
#include <cerrno>
#include <cstddef>
#define UNUSED __attribute__((unused))
struct _reent { int _errno; };
struct DIR_ENTRY { bool directory; };
struct FILE_STRUCT { DIR_ENTRY *entry; size_t offset; bool inUse; };
DIR_ENTRY entry = {false};
DIR_ENTRY *entry_from_path(const char *p) { return *p ? &entry : nullptr; }
bool is_dir(DIR_ENTRY *p) { return p->directory; }
'''
devoptab += function('source/DiskOperations/gcfst.c', 'static int _FST_open_r(')
devoptab += function('source/DiskOperations/gcfst.c', 'static int _FST_close_r(')
devoptab += r'''
int main() {
 _reent r = {}; FILE_STRUCT file = {};
 assert(_FST_open_r(&r, &file, "", 0, 0) == -1 && r._errno == ENOENT);
 entry.directory = true;
 assert(_FST_open_r(&r, &file, "dir", 0, 0) == -1 && r._errno == EISDIR);
 entry.directory = false;
 // Open returns status, while subsequent callbacks receive the same file state.
 assert(_FST_open_r(&r, &file, "file", 0, 0) == 0);
 assert(file.entry == &entry && file.offset == 0 && file.inUse);
 assert(_FST_close_r(&r, &file) == 0 && !file.inUse);
 assert(_FST_close_r(&r, &file) == -1 && r._errno == EBADF);
}
'''

with tempfile.TemporaryDirectory(prefix='wiixplorer-tests-') as directory:
    directory = Path(directory)
    for name, code in [('transfer', transfer), ('gpt', gpt), ('partition', partition), ('http', http), ('devoptab', devoptab), ('exit', exit_code), ('heap', heap), ('smoke', smoke)]:
        is_c = name == 'http'
        source = directory / (name + ('.c' if is_c else '.cpp'))
        source.write_text(code)
        binary = directory / name
        compiler = os.environ.get('CC', 'cc') if is_c else os.environ.get('CXX', 'c++')
        subprocess.run([compiler, '-std=c11' if is_c else '-std=c++11', '-Wall', '-Wextra',
                        '-fsanitize=address,undefined', str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], cwd=directory, check=True)
        print(name + ': passed')
