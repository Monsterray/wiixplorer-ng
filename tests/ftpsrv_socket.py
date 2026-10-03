#!/usr/bin/env python3
"""Exercise the actual ftpsrv Wii socket adapter's IOS-specific semantics."""
from pathlib import Path
import os, subprocess, tempfile
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='wx-ftpsrv-socket-') as directory:
    t=Path(directory);(t/'ogc').mkdir()
    (t/'network.h').write_text(r'''#pragma once
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <stdint.h>
typedef uint64_t u64;
struct pollsd {int socket;unsigned events,revents;};
int net_socket(int,int,int);int net_accept(int,struct sockaddr*,socklen_t*);
int net_recv(int,void*,size_t,int);int net_send(int,const void*,size_t,int);
int net_fcntl(int,int,int);int net_setsockopt(int,int,int,const void*,socklen_t);
int net_shutdown(int,int);int net_close(int);int net_poll(struct pollsd*,size_t,int);
int net_bind(int,struct sockaddr*,socklen_t);int net_connect(int,struct sockaddr*,socklen_t);
int net_listen(int,int);int net_getsockname(int,struct sockaddr*,socklen_t*);
''')
    (t/'ogc/ipc.h').write_text('#pragma once\nint IOS_Open(const char*,int);int IOS_Close(int);\n')
    (t/'ogc/lwp_watchdog.h').write_text('#pragma once\n#include <stdint.h>\nextern uint64_t ticks;\ninline uint64_t gettime(){return ticks+=10;}\ninline uint64_t secs_to_ticks(unsigned n){return n*1000;}\n')
    (t/'test.cpp').write_text(r'''
#include <cassert>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include "FTPOperations/FtpsrvConfig.h"
#include "FTPOperations/ftpsrv/ftpsrv_socket.h"
uint64_t ticks=0;unsigned reported=8;int flags=0,closed=0,sends=0;bool stopping=true,option_ok=true,emulated=false;
int wx_ftp_stopping(){return stopping;}
int net_socket(int,int,int){return 0;}
int net_accept(int,struct sockaddr*,socklen_t*){return -EAGAIN;}
int net_recv(int,void*,size_t n,int){assert(n<=16384);return -EAGAIN;}
int net_send(int fd,const void*,size_t n,int){assert(fd==0&&n<=4096);assert(emulated ? flags&4 : !(flags&4));++sends;return n;}
int net_fcntl(int,int command,int v){if(command==F_GETFL)return flags;flags=v;return 0;}
int net_setsockopt(int,int,int option,const void *value,socklen_t){if(option==SO_SNDLOWAT){assert(*(const unsigned*)value==4096);return option_ok?0:-EINVAL;}return 0;}
int net_shutdown(int,int){return 0;}int net_close(int fd){assert(fd==0);++closed;return 0;}
int net_poll(pollsd *p,size_t n,int){for(size_t i=0;i<n;++i)p[i].revents=reported;return 1;}
int net_bind(int,struct sockaddr*,socklen_t){return 0;}int net_connect(int,struct sockaddr*,socklen_t){return 0;}
int net_listen(int,int){return 0;}int net_getsockname(int,struct sockaddr*,socklen_t*){return 0;}
int IOS_Open(const char*name,int){assert(!strcmp(name,"/dev/dolphin"));return emulated?1:-1;}
int IOS_Close(int){return 0;}
int main(){
 FtpSocket s={};char data[32768]={};assert(ftp_socket_open(&s,AF_INET,SOCK_STREAM,0)==0&&s.valid&&flags==4);
 flags=6;reported=0;assert(ftp_socket_send(&s,data,sizeof(data),0)==-1&&errno==EAGAIN&&sends==0&&flags==6);
 reported=8;assert(ftp_socket_send(&s,data,sizeof(data),0)==4096&&sends==1&&flags==6);
 assert(ftp_socket_set_nonblocking_enable(&s,0)==0&&flags==2);ftp_socket_set_nonblocking_enable(&s,1);
 FtpSocketPollEntry entry={&s,FtpSocketPollType_IN,(FtpSocketPollType)0};FtpSocketPollFd fds={};
 reported=0x40;ftp_socket_poll(&entry,&fds,1,0);assert(entry.revents&FtpSocketPollType_IN);assert(!(entry.revents&FtpSocketPollType_ERROR));
 entry.events=FtpSocketPollType_OUT;ftp_socket_poll(&entry,&fds,1,0);assert(entry.revents&FtpSocketPollType_ERROR);
 reported=0;s.listening=1;entry.events=FtpSocketPollType_IN;ftp_socket_poll(&entry,&fds,1,0);assert(entry.revents&FtpSocketPollType_IN);
 ftp_socket_close(&s);assert(closed==1&&!s.valid);ftp_socket_close(&s);assert(closed==1);
 option_ok=false;assert(ftp_socket_open(&s,AF_INET,SOCK_STREAM,0)<0&&!s.valid&&closed==2);
 emulated=true;assert(ftp_socket_open(&s,AF_INET,SOCK_STREAM,0)==0&&s.emulated);assert(ftp_socket_send(&s,data,100,0)==100);ftp_socket_close(&s);
 FtpSocket out={};sockaddr addr={};size_t length=sizeof(addr);assert(ftp_socket_accept(&out,&s,&addr,&length)<0&&!out.valid);
}
''')
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-DGEKKO','-fsanitize=address,undefined','-I'+str(t),'-I'+str(ROOT/'source'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
    subprocess.run([str(t/'test')],check=True,timeout=10)
print('ftpsrv Wii sockets: native capacity gate, mode restoration, fd zero, EOF versus error, periodic accept and emulator-only fallback passed')
