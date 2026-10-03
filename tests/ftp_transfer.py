#!/usr/bin/env python3
"""Exercise production FTP upload staging, resume, append and failure cleanup."""
from pathlib import Path
import os
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]

def function(source, signature):
    start=source.index(signature); end=source.index('{',start)+1; depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}'); end+=1
    return source[start:end]

ftp=(ROOT/'source/FTPOperations/ftpii/ftp.c').read_text()
net=(ROOT/'source/FTPOperations/ftpii/net.c').read_text()
code=r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <cerrno>
#include <sys/stat.h>
#include <unistd.h>
using u64=uint64_t;using u32=uint32_t;using s32=int32_t;
#define MIN(a,b) ((a)<(b)?(a):(b))
#define MAX_NET_BUFFER_SIZE (60*1024)
static u32 NET_BUFFER_SIZE=MAX_NET_BUFFER_SIZE;
static char *transfer_buffer;
void *testAlign(size_t alignment,size_t size){void*p=nullptr;return posix_memalign(&p,alignment,size)?nullptr:p;}
#define memalign testAlign
static bool canceled=false,failClose=false,failWrite=false;
int wx_transfer_cancelled(){return canceled;}
u64 gettime(){return 0;} u64 secs_to_ticks(u64 s){return s;}
const char *input="";size_t position=0;
s32 net_read(s32,void *p,u32 n){size_t left=strlen(input)-position;if(n>left)n=left;memcpy(p,input+position,n);position+=n;return n;}
struct client_t {char cwd[1024]={};off_t restart_marker=0;void *data_connection_callback_arg=nullptr;};
char *to_real_path(char *,char *path){return strdup(path);}
s32 write_reply(client_t*,int code,const char*){return code;}
s32 prepare_data_connection(client_t *c,void*,void *arg,void*){c->data_connection_callback_arg=arg;return 150;}
int checkedClose(FILE *f){int r=fclose(f);return failClose?EOF:r;}
size_t checkedWrite(const void *p,size_t s,size_t n,FILE *f){return failWrite?0:fwrite(p,s,n,f);}
#define fclose checkedClose
#define fwrite checkedWrite
'''
code+='#include "'+str(ROOT/'source/FileOperations/TransferFile.h')+'"\n'
code+=function(net,'s32 init_ftp_buffers(')+'\n'
code+=function(net,'void cleanup_ftp_buffers(')+'\n'
code+=function(net,'s32 recv_to_file(')+'\n'
start=ftp.index('typedef struct {\n    FILE *file;');end=ftp.index('} upload_t;',start)+len('} upload_t;')
code+=ftp[start:end]+'\n'
for signature in ('static void abort_upload(', 'static s32 receive_upload(', 'static s32 start_upload('):
    code+=function(ftp,signature)+'\n'
code+=r'''
#undef fclose
#undef fwrite
void put(const char *data){FILE *f=fopen("./dest","wb");assert(f);fputs(data,f);assert(fclose(f)==0);}
void expect(const char *data){char buffer[100]={};FILE *f=fopen("./dest","rb");assert(f);fread(buffer,1,99,f);fclose(f);assert(!strcmp(data,buffer));}
void finish(client_t &c,const char *data){input=data;position=0;assert(receive_upload(1,c.data_connection_callback_arg)==(s32)strlen(data));if (*data) assert(receive_upload(1,c.data_connection_callback_arg)==0);abort_upload(c.data_connection_callback_arg);c.data_connection_callback_arg=nullptr;}
int main(){
 assert(transfer_buffer==nullptr);assert(init_ftp_buffers()==0);cleanup_ftp_buffers();assert(transfer_buffer==nullptr);assert(init_ftp_buffers()==0);atexit(cleanup_ftp_buffers);
 client_t c;char path[]="./dest";
 put("original");assert(start_upload(&c,path,false)==150);expect("original");finish(c,"new");expect("new");
 assert(start_upload(&c,path,false)==150);abort_upload(c.data_connection_callback_arg);c.data_connection_callback_arg=nullptr;expect("new");
 assert(start_upload(&c,path,false)==150);input="";position=0;failClose=true;assert(receive_upload(1,c.data_connection_callback_arg)<0);failClose=false;abort_upload(c.data_connection_callback_arg);expect("new");
 assert(start_upload(&c,path,false)==150);input="bad";position=0;failWrite=true;assert(receive_upload(1,c.data_connection_callback_arg)<0);failWrite=false;abort_upload(c.data_connection_callback_arg);expect("new");
 assert(start_upload(&c,path,true)==150);finish(c," appended");expect("new appended");
 put("abcdefghi");c.restart_marker=3;assert(start_upload(&c,path,false)==150);finish(c,"x");expect("abcxefghi");
 c.restart_marker=100;c.data_connection_callback_arg=nullptr;assert(start_upload(&c,path,false)==550);expect("abcxefghi");
 assert(start_upload(&c,path,false)==150);canceled=true;assert(receive_upload(1,c.data_connection_callback_arg)==-EINTR);canceled=false;abort_upload(c.data_connection_callback_arg);expect("abcxefghi");
 assert(start_upload(&c,path,false)==150);finish(c,"");expect("");
 assert(access("./dest.wx-transfer-0",F_OK)!=0);
}
'''
# The original C server uses generic callback pointers; test with equivalent
# typed adapters so host C++ can compile the extracted production routines.
code=code.replace('upload_t *u = arg;', 'upload_t *u = (upload_t *)arg;').replace('upload_t *u = calloc(1, sizeof(*u));','upload_t *u = (upload_t *)calloc(1, sizeof(*u));')
code=code.replace('prepare_data_connection(client_t *c,void*,void *arg,void*)','prepare_data_connection(client_t *c,s32(*)(s32,void*),void *arg,void(*)(void*))')
client_source=(ROOT/'source/FTPOperations/ftp_devoptab.c').read_text()
client_code=r"""
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cstdarg>
#include <cerrno>
#include <fcntl.h>
using u32=uint32_t;using u64=uint64_t;using s32=int32_t;
#define FTP_MAXPATH 1024
#define MAX_FTP_MOUNTED 1
#define INVALID_SOCKET -1
#define SOCKET s32
#define NET_ASSERT(x) assert(x)
#define NET_PRINTF(...) ((void)0)
struct FTPFILESTRUCT {off_t offset=0,size=100;char filename[1024]="/test";int envIndex=0,flags=O_TRUNC;bool transferFailed=false,wrote=false;};
struct ftp_env {int data_socket=-1;FTPFILESTRUCT *write_file=nullptr;const char *share="",*currentpath="/";};
ftp_env FTPEnv[1];
off_t last_off=0;
int ack=226,locks=0,readSize=3;bool sendOkay=true,halfClosed=false;
void _FTP_lock(){++locks;}void _FTP_unlock(){assert(locks>0);--locks;}
int net_close_blocking(int){return 0;}int net_close(int){return 0;}
int net_shutdown(int,int how){assert(how==1);halfClosed=true;return 0;}
int ftp_get_response(ftp_env*){return ack;}
int ftp_execute_open(ftp_env *env,char*,const char*,off_t,int *socket){env->data_socket=*socket=5;return 0;}
int SocketRecv(int,char*,off_t,bool){return readSize;}
bool SocketSend(int,const char*,off_t){return sendOkay;}
void ReplaceForwardSlash(char *p){for(;*p;++p)if(*p=='\\')*p='/';}
"""
for signature in ('static int format_ftp_command(', 'static int ftp_close_data(', 'static bool FTP_ReadFile(', 'static bool FTP_WriteFile(', 'static bool FTP_CloseFile(', 'static bool ftp_absolute_path_no_device('):
    client_code+=function(client_source,signature)+'\n'
client_code+=r"""
int main(){
 FTPFILESTRUCT file;char buffer[8];
 readSize=2;assert(!FTP_ReadFile(buffer,3,0,&file));assert(!locks);
 readSize=3;assert(FTP_ReadFile(buffer,3,0,&file));assert(last_off==3);
 sendOkay=false;assert(!FTP_WriteFile(buffer,3,0,&file));assert(file.transferFailed&&!locks);
 file.transferFailed=false;sendOkay=true;assert(FTP_WriteFile(buffer,3,0,&file));
 ack=552;assert(!FTP_CloseFile(&file));assert(halfClosed&&FTPEnv[0].write_file==nullptr&&!locks);
 file.transferFailed=false;file.wrote=false;ack=226;assert(FTP_CloseFile(&file));assert(file.wrote);
 assert(FTPEnv[0].data_socket==-1);
 char path[FTP_MAXPATH];assert(ftp_absolute_path_no_device("ftp1:/test",path,0)&&!strcmp(path,"/test"));
 assert(!ftp_absolute_path_no_device("ftp1:/bad\r\nDELE x",path,0));
 assert(!ftp_absolute_path_no_device("/test",path,2));
 char large[FTP_MAXPATH+1];memset(large,'x',sizeof(large)-1);large[sizeof(large)-1]=0;
 assert(!ftp_absolute_path_no_device(large,path,0));
 assert(format_ftp_command(buffer,sizeof(buffer),"%s",large)<0&&!buffer[0]);
}
"""
with tempfile.TemporaryDirectory(prefix='wx-ftp-transfer-') as directory:
    tmp=Path(directory)
    for name,body in [('server',code),('client',client_code)]:
        (tmp/'test.cpp').write_text(body)
        subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-fsanitize=address,undefined',str(tmp/'test.cpp'),'-o',str(tmp/'test')],check=True)
        subprocess.run([str(tmp/'test')],cwd=tmp,check=True,timeout=10)
print('FTP transfer: replacement, abort, failed close/write, append, resume bounds, cancellation and empty files passed')
