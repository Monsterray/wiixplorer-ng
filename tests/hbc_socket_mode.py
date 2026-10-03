#!/usr/bin/env python3
"""Exercise SDK accept/read setup with POSIX non-inheriting accepted sockets."""
from pathlib import Path
import os,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.deps/work/hbc-agent/hbc-reborn-3b1e9a4e04fbb1afb98f516a2446ef9789877f8f'
if not (BASE/'sdk/hbc_agent/agent.c').exists():
 print('HBC socket checks skipped: run make deps first')
 raise SystemExit(0)
def function(source,signature):
 start=source.index(signature);end=source.index('{',start)+1;depth=1
 while depth:
  depth+=(source[end]=='{')-(source[end]=='}');end+=1
 return source[start:end]
agent=(BASE/'sdk/hbc_agent/agent.c').read_text()
a=agent.index('\t\ts = net_accept(ls,');b=agent.index('\n\t\t// Like HBC',a)
block=agent[a:b]
tcp=(BASE/'channel/channelapp/source/tcp.c').read_text()
code=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <cerrno>
#include <sys/socket.h>
#include <netinet/in.h>
using u8=uint8_t;using u32=uint32_t;using s32=int32_t;using s64=int64_t;using mutex_t=int;
#define TCP_IO_BLOCK 16384
#define TCP_BLOCK_SIZE 65536
#define gprintf(...) ((void)0)
s64 woke=0,idle_ticks=0;u32 idle_wakes=0;
int flags=0;bool failFlags=false,closed=false;
u32 trace_len=0;char trace[512]={},last_failure[512]={};s64 ticks=0;
s64 gettime(){return ++ticks;}s64 diff_ticks(s64 a,s64 b){return b-a;}s64 ticks_to_millisecs(s64 v){return v;}
void trace_add(const char*,...){ }void LWP_MutexLock(int){}void LWP_MutexUnlock(int){}
u32 tcp_wait(s32,u32,s32 ms){ticks+=ms;return 0;}
#define TCP_POLLIN 3
s32 net_read(s32,void*,u32){assert(flags==4);return -EAGAIN;}
s32 net_accept(s32,sockaddr*,u32*){flags=0;return 7;}
s32 net_fcntl(s32,int operation,int value){if(operation==F_GETFL)return flags;if(failFlags)return -EIO;flags=value;return 0;}
s32 net_close(s32){closed=true;return 0;}void net_deinit(){}
'''
code+=function(tcp,'bool tcp_read_timeout (')+'\n'
code+='''void run(){s32 ls=1,s;struct sockaddr_in sa={};u32 len_sa=sizeof(sa);
 for(int attempt=0;attempt<1;++attempt){
'''+block+'''
 u8 data[12];assert(!tcp_read_timeout(s,data,sizeof(data),nullptr,nullptr,10));
 }
}
int main(){run();assert(flags==4 && !closed);failFlags=true;run();assert(closed);}
'''
# Until the fix, only the real read assertion is needed to reproduce the bug.
if 'net_fcntl' not in block:code=code.replace('failFlags=true;run();assert(closed);','')
with tempfile.TemporaryDirectory(prefix='wx-hbc-accepted-') as tmp:
 p=Path(tmp);(p/'test.cpp').write_text(code)
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-fsanitize=address,undefined',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=10)
print('HBC accepted socket: non-inherited mode, idle read deadline and failed mode setup cleanup passed')
