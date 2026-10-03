#!/usr/bin/env python3
"""Check production patched NFS completion, count bounds, and lock release."""
from pathlib import Path
import os
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'.deps/work/nfs/source/nfs_file.c'
if not path.exists():
    print('NFS transfer checks skipped: run scripts/build-deps.py first')
    raise SystemExit(0)
source=path.read_text()
def function(signature):
    start=source.index(signature);end=source.index('{',start)+1;depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]
code=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cerrno>
#include <sys/types.h>
#include <cstdio>
struct _reent{int _errno=0;};using mutex_t=int;
struct fhandle3{int len=4;};struct object_attributes{char bytes[84];};
struct NFSMOUNT{char buffer[1024];u_int32_t bufferlen=1024;int rtpref=8192,rtmult=0,wtpref=65536,wtmult=0,nfs_port=2049;mutex_t lock=1;};
struct NFS_FILE_STRUCT{NFSMOUNT *nfsmount;fhandle3 handle;uint32_t currentPosition=0,size=0;bool read=true,write=true;bool isnew=false;int shouldcommit=0;bool hasWriteVerifier=false;int64_t writeVerifier=0;};
#define PROGRAM_NFS 1
#define PROCEDURE_COMMIT 2
#define PROCEDURE_WRITE 3
#define PROCEDURE_READ 4
#define AUTH_UNIX 1
#define WRITE_UNSTABLE 0
int locks=0,calls=0,procedure=0;char response[1024];int responseSize;
void _NFS_lock(mutex_t*){assert(locks==0);++locks;}
void _NFS_unlock(mutex_t*){assert(locks==1);--locks;}
int rpc_create_header(NFSMOUNT*,int,int,int op,int){procedure=op;return 24;}
int rpc_write_fhandle(NFSMOUNT*,int,fhandle3*){return 8;}
int rpc_write_long(NFSMOUNT*,int,int64_t){return 8;}
int rpc_write_int(NFSMOUNT*,int,int32_t){return 4;}
int rpc_write_block(NFSMOUNT*,int,void*,int n){return 4+n;}
int udp_sendrecv(NFSMOUNT *m,int,int){++calls;assert(calls<10);memset(m->buffer,0,sizeof(m->buffer));memcpy(m->buffer,response,responseSize);return responseSize;}
int rpc_parse_header(NFSMOUNT*,int *n){*n=24;return 0;}
int rpc_read_int(NFSMOUNT *m,int offset,int32_t *n){assert(offset>=0&&offset+4<=1024);memcpy(n,m->buffer+offset,4);return 4;}
int rpc_read_long(NFSMOUNT *m,int offset,int64_t *n){assert(offset>=0&&offset+8<=1024);memcpy(n,m->buffer+offset,8);return 8;}
void reset(){memset(response,0,sizeof(response));responseSize=24;calls=0;}
void value(int32_t n){memcpy(response+responseSize,&n,4);responseSize+=4;}
void writeReply(int count,int status=0,int64_t verifier=7){reset();value(status);value(0);value(0);value(count);value(2);memcpy(response+responseSize,&verifier,8);responseSize+=8;}
void readReply(int count,int eof,int opaque){reset();value(0);value(0);value(count);value(eof);value(opaque);memcpy(response+responseSize,"abc",3);responseSize+=3;}
'''
for signature in ('int32_t _NFS_close_r (','ssize_t _NFS_write_r (','ssize_t _NFS_read_r (','off_t _NFS_seek_r ('):
    code+=function(signature)+'\n'
code+=r'''
int main(){
 NFSMOUNT mount;NFS_FILE_STRUCT file;file.nfsmount=&mount;_reent r;char bytes[8]={};
 writeReply(0);assert(_NFS_write_r(&r,&file,"abc",3)==-1&&r._errno==EIO&&!locks);
 writeReply(4);assert(_NFS_write_r(&r,&file,"abc",3)==-1&&!locks);
 writeReply(3,13);assert(_NFS_write_r(&r,&file,"abc",3)==-1&&r._errno==13&&!locks);
 writeReply(3);assert(_NFS_write_r(&r,&file,"abc",3)==3&&!locks&&file.shouldcommit);
 reset();value(13);assert(_NFS_close_r(&r,&file)==-1&&r._errno==13&&!locks);
 writeReply(3,0,8);assert(_NFS_write_r(&r,&file,"abc",3)==-1&&r._errno==EIO&&!locks);
 reset();value(0);value(0);value(0);int64_t verifier=8;memcpy(response+responseSize,&verifier,8);responseSize+=8;assert(_NFS_close_r(&r,&file)==-1&&r._errno==EIO&&!locks);
 verifier=7;memcpy(response+responseSize-8,&verifier,8);assert(_NFS_close_r(&r,&file)==0&&!locks);
 file=NFS_FILE_STRUCT();file.nfsmount=&mount;
 readReply(0,0,0);assert(_NFS_read_r(&r,&file,bytes,3)==-1&&!locks);
 readReply(4,1,4);assert(_NFS_read_r(&r,&file,bytes,3)==-1&&!locks);
 readReply(3,1,2);assert(_NFS_read_r(&r,&file,bytes,3)==-1&&!locks);
 readReply(3,1,3);assert(_NFS_read_r(&r,&file,bytes,3)==3&&!strcmp(bytes,"abc")&&!locks);
 writeReply(3);char large[9]={};assert(_NFS_write_r(&r,&file,large,sizeof(large))==9&&calls==3&&!locks);
 assert(_NFS_seek_r(&r,&file,-1,SEEK_SET)==-1&&!locks);
 assert(_NFS_seek_r(&r,&file,0x100000000LL,SEEK_SET)==-1&&!locks);
 assert(_NFS_seek_r(&r,&file,4,SEEK_SET)==4&&!locks);
 assert(_NFS_read_r(&r,&file,bytes,0x80000000UL)==-1&&r._errno==EFBIG&&!locks);
 file.currentPosition=0xffffffff;assert(_NFS_read_r(&r,&file,bytes,3)==-1&&r._errno==EFBIG&&!locks);
 assert(_NFS_write_r(&r,&file,"abc",3)==-1&&r._errno==EFBIG&&!locks);
}
'''
with tempfile.TemporaryDirectory(prefix='wx-nfs-transfer-') as directory:
    tmp=Path(directory);(tmp/'test.cpp').write_text(code)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-fsanitize=address,undefined',str(tmp/'test.cpp'),'-o',str(tmp/'test')],check=True)
    subprocess.run([str(tmp/'test')],check=True,timeout=10)
print('NFS transfer: COMMIT failures, zero/oversized counts, short payload, 32-bit position bounds and error unlocks passed')
