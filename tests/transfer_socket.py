#!/usr/bin/env python3
"""Exercise production socket capacity polling and transfer deadlines."""
from pathlib import Path
import os
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='wx-transfer-socket-') as directory:
    tmp = Path(directory)
    (tmp/'Controls').mkdir(); (tmp/'ogc').mkdir()
    (tmp/'gctypes.h').write_text('#pragma once\n#include <cstdint>\nusing u8=uint8_t;using u32=uint32_t;using u64=uint64_t;using s32=int32_t;\n')
    (tmp/'Controls/Application.h').write_text('#pragma once\nextern bool closing;\nstruct Application { static bool isClosing() {return closing;} };\n')
    (tmp/'ogc/lwp_watchdog.h').write_text('#pragma once\n#include <gctypes.h>\nextern u64 ticks;\ninline u64 gettime(){return ticks;}\ninline u64 secs_to_ticks(u64 s){return s*1000;}\n')
    (tmp/'ogc/ipc.h').write_text('#pragma once\n#include <gctypes.h>\ns32 IOS_Open(const char*,u32);s32 IOS_Close(s32);\n')
    (tmp/'network.h').write_text('''#pragma once
#include <gctypes.h>
#define SOL_SOCKET 65535
#define SO_SNDLOWAT 0x1003
struct pollsd{s32 socket;u32 events,revents;};
s32 net_fcntl(s32,int,int);s32 net_write(s32,const void*,u32);s32 net_read(s32,void*,u32);
s32 net_shutdown(s32,int);s32 net_poll(pollsd*,int,int);
s32 net_setsockopt(s32,u32,u32,const void*,u32);
''')
    harness=r'''
#include <cassert>
#include <cstring>
#include <fcntl.h>
#include <errno.h>
#include "network/TransferSocket.h"
#include <network.h>
bool closing=false;
u64 ticks=0;
int mode=0, flags=4, writes=0;
bool ready=false;
s32 IOS_Open(const char *path,u32){assert(!strcmp(path,"/dev/dolphin"));return mode==7||mode==9?1:-1;}
s32 IOS_Close(s32 d){assert(d==1);return 0;}
s32 net_fcntl(s32,int op,int val){if(op==F_GETFL)return flags;flags=val;return 0;}
s32 net_shutdown(s32,int){return 0;}
s32 net_setsockopt(s32,u32 level,u32 option,const void *p,u32 n){
 assert(level==SOL_SOCKET && option==SO_SNDLOWAT && n==4 && *(const u32*)p==4096);
 return mode==5||mode==7||mode==9 ? -EINVAL : 0;
}
s32 net_poll(pollsd *p,int,int ms){ticks+=ms;p->revents=mode==1?0:p->events;ready=p->revents&8;return 1;}
s32 net_write(s32,const void*,u32 len){
 assert((mode==7||mode==9 ? flags==4 : flags==0 && ready) && len<=4096);++writes;ready=false;
 if(mode==9)return -EAGAIN;
 if(mode==10)return len;
 if(mode==11){ticks+=2000;return 1;}
 if(mode==12){ticks+=5000;return 1;}
 if(mode==2)return 0;
 if(mode==6)return len+1;
 return len>7?7:len;
}
s32 net_read(s32,void *p,u32 len){assert(flags==4 && len<=16384);if(mode==3)return -EAGAIN;if(mode==4)return 0;memset(p,42,len);return len;}
int main(){
 char data[32]={};assert(wx_transfer_write(1,data,32)==32);assert(flags==4);
 int before=writes;mode=1;assert(wx_transfer_write(1,data,32)==-ETIMEDOUT);assert(writes==before && flags==4);
 mode=2;assert(wx_transfer_write(1,data,32)==-EIO);assert(flags==4);
 mode=3;assert(wx_transfer_read(1,data,32)==-ETIMEDOUT);
 mode=4;assert(wx_transfer_read(1,data,32)==0);
 mode=5;assert(wx_transfer_write(1,data,32)==-EINVAL);
 mode=6;assert(wx_transfer_write(1,data,32)==-EIO);
 mode=7;flags=0;assert(wx_transfer_write(1,data,32)==32);assert(flags==0);
 mode=9;assert(wx_transfer_write(1,data,32)==-ETIMEDOUT);assert(flags==0);
 mode=10;char large[300*1024]={};assert(wx_transfer_write(1,large,sizeof(large))==256*1024);
 mode=11;assert(wx_transfer_write(1,data,32)==32);
 mode=12;assert(wx_transfer_write(1,data,32)==-ETIMEDOUT);
 mode=0;flags=0;assert(wx_transfer_write(1,data,32)==32);assert(flags==0);
 closing=true;assert(wx_transfer_read(1,data,32)==-EINTR);assert(wx_transfer_write(1,data,32)==-EINTR);
 assert(wx_transfer_write(1,data,0)==0);
 assert(wx_transfer_write(1,nullptr,32)==-EINVAL);assert(wx_transfer_read(1,nullptr,32)==-EINVAL);
}
'''
    (tmp/'test.cpp').write_text(harness)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-fsanitize=address,undefined',
                    '-I'+str(tmp),'-I'+str(ROOT/'source'),str(ROOT/'source/network/TransferSocket.cpp'),
                    str(tmp/'test.cpp'),'-o',str(tmp/'test')],check=True)
    subprocess.run([str(tmp/'test')],check=True,timeout=10)
print('Transfer socket: capacity gating, deadline, partial/zero/invalid writes, mode preservation, idle read, EOF and cancellation passed')
