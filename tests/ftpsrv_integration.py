#!/usr/bin/env python3
"""Run the real ftpsrv core, DeviceHandler VFS and lazy FTPServer on host sockets."""
from pathlib import Path
import ftplib
import io
import json
import os
import socket
import subprocess
import tempfile
import time
ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='wx-ftpsrv-') as directory:
    tmp = Path(directory)
    def write(path, text):
        p = tmp/path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
    write('gctypes.h', '#pragma once\n#include <cstdint>\nusing s32=int32_t;using u32=uint32_t;\n')
    write('ogc/lwp.h', r'''#pragma once
#include <pthread.h>
#include <atomic>
struct HostThread { pthread_t thread; };
using lwp_t=HostThread*;
#define LWP_THREAD_NULL nullptr
extern std::atomic<int> threads;
inline int LWP_CreateThread(lwp_t *out,void *(*fn)(void*),void *arg,void*,unsigned,int) {
 auto t=new HostThread;int rc=pthread_create(&t->thread,nullptr,fn,arg);
 if(rc){delete t;return -rc;}*out=t;++threads;return 0;
}
inline int LWP_JoinThread(lwp_t t,void **out){int rc=pthread_join(t->thread,out);delete t;--threads;return rc;}
''')
    write('Controls/CMutex.h', '#pragma once\n#include <mutex>\nclass CMutex {std::recursive_mutex m;public:CMutex(bool){}void lock(){m.lock();}void unlock(){m.unlock();}};\n')
    write('malloc.h', '#pragma once\n#include <stdlib.h>\ninline void* memalign(size_t n,size_t size){void*p=nullptr;return posix_memalign(&p,n,size)?nullptr:p;}\n')
    write('Settings.h', r'''#pragma once
struct Config {
 struct {short AutoStart;char User[50];short Anonymous;unsigned IdleTimeout;char Password[50];unsigned short Port;} FTPServer;
 short MountISFS,ISFSWriteAccess;
};
extern Config Settings;
''')
    device_header=(ROOT/'source/DeviceControls/DeviceHandler.hpp').read_text()
    enum=device_header[device_header.index('enum\n'):device_header.index('class DeviceHandler')]
    write('DeviceControls/DeviceHandler.hpp', '#pragma once\n#include <atomic>\n'+enum+r'''
extern std::atomic<int> device_calls;
extern bool mounted[MAXDEVICES];
class DeviceHandler {public:static DeviceHandler*Instance(){static DeviceHandler d;return &d;}bool IsInserted(int dev){++device_calls;return mounted[dev];}};
''')
    write('Language/gettext.h', '#pragma once\ninline const char *tr(const char*s){return s;}\n')
    write('Tools/gxprintf.h', '#pragma once\n#include <stdio.h>\n#define gxprintf(...) fprintf(stderr,__VA_ARGS__)\n')
    write('network/networkops.h', '#pragma once\nbool IsNetworkInit();void Initialize_Network();\n')
    # Force short sends, including fragmented control replies. No test-only
    # branches or callbacks are added to the production implementation.
    write('core.c', '#include "'+str(ROOT/'source/FTPOperations/ftpsrv/ftpsrv.c')+'"\nint test_core_active(void){return ftp_state!=NULL;}\n')
    write('app.cpp', r'''
#include <atomic>
#include <cstdio>
#include <cstring>
#include <string>
#include <iostream>
#include <sys/socket.h>
#include "ogc/lwp.h"
#include "Settings.h"
#include "DeviceControls/DeviceHandler.hpp"
#include "FTPOperations/FTPServer.h"
#include "Diagnostics/MemoryProbes.h"
Config Settings={};std::atomic<int> threads(0),device_calls(0);bool mounted[MAXDEVICES]={};
std::atomic<uint64_t> memoryLive(0),memoryPeak(0),memoryEvents(0);
extern "C" void wx_memory_record(unsigned,uintptr_t address,uint64_t bytes,int allocate){
 if(!address)return;
 ++memoryEvents;
 if(allocate){auto live=memoryLive.fetch_add(bytes)+bytes;auto peak=memoryPeak.load();while(live>peak && !memoryPeak.compare_exchange_weak(peak,live)){} }
 else {auto live=memoryLive.fetch_sub(bytes);if(live<bytes)abort();}
}
bool IsNetworkInit(){return true;}void Initialize_Network(){abort();}
extern "C" int test_core_active(void);
extern "C" ssize_t wx_test_send(int fd,const void*b,size_t n,int flags){return send(fd,b,n>1024?(n>2048?2048:n):(n>17?17:n),flags);}
int main(int argc,char **argv){
 Settings.FTPServer.Port=atoi(argv[1]);Settings.FTPServer.IdleTimeout=2;
 strcpy(Settings.FTPServer.User,"wiixplorer");strcpy(Settings.FTPServer.Password,"private-test-password");
 Settings.MountISFS=1;Settings.ISFSWriteAccess=1;mounted[SD]=mounted[USB1]=mounted[NAND]=true;
 auto server=FTPServer::Instance();std::string command;
 while(std::getline(std::cin,command)){
  if(command=="enable")server->StartupFTP();
  if(command=="disable")server->ShutdownFTP();
  if(command=="hide_nand")Settings.MountISFS=0;
  if(command=="anon")Settings.FTPServer.Anonymous=1;
  if(command=="exit"){FTPServer::DestroyInstance();return 0;}
  printf("{\"running\":%d,\"status\":%d,\"cycles\":%u,\"threads\":%d,\"core\":%d,\"devices\":%d,\"memory_live\":%llu,\"memory_peak\":%llu,\"memory_events\":%llu}\n",
   server->isRunning(),server->status(),server->cycles(),threads.load(),test_core_active(),device_calls.load(),(unsigned long long)memoryLive.load(),(unsigned long long)memoryPeak.load(),(unsigned long long)memoryEvents.load());
  fflush(stdout);
 }
 FTPServer::DestroyInstance();return 0;
}
''')
    flags=['-g','-fsanitize=address,undefined','-I'+str(tmp),'-I'+str(ROOT/'source'),'-pthread','-DWX_PROBE_LEVEL=1','-DWX_PROBE_NETWORK=1','-DWX_PROBE_CPU=0','-DWX_PROBE_GPU=0','-DWX_PROBE_IO=0','-DWX_PROBE_THREADS=0']
    subprocess.run([os.environ.get('CC','cc'),'-std=gnu99',*flags,'-Dsend=wx_test_send','-c',str(tmp/'core.c'),'-o',str(tmp/'core.o')],check=True)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++11',*flags,str(ROOT/'source/FTPOperations/FTPServer.cpp'),str(ROOT/'source/FTPOperations/WiiXplorerFtpVfs.cpp'),str(tmp/'app.cpp'),str(tmp/'core.o'),'-o',str(tmp/'server')],check=True)
    for dev in ('sd:','usb1:','nand:'):(tmp/dev).mkdir()
    (tmp/'nand:/secret').write_bytes(b'read-only')
    (tmp/'sd:/preserve').write_bytes(b'old destination')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    with (tmp/'log').open('w+') as log:
        proc=subprocess.Popen([str(tmp/'server'),str(port)],cwd=tmp,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True)
        def command(cmd):
            proc.stdin.write(cmd+'\n');proc.stdin.flush()
            line=proc.stdout.readline()
            assert line,(proc.poll(),(tmp/'log').read_text())
            return json.loads(line)
        def connect(user='wiixplorer',password='private-test-password'):
            ftp=ftplib.FTP();ftp.connect('127.0.0.1',port,timeout=5);ftp.login(user,password);return ftp
        def refused():
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.2): pass
            except OSError:return
            raise AssertionError('disabled FTP still listens')
        try:
            before=command('status');time.sleep(.12);after=command('status')
            assert before==after and before['threads']==before['core']==before['cycles']==before['devices']==0 and before['memory_live']==before['memory_events']==0
            refused()
            with socket.socket() as occupied:
                occupied.bind(('0.0.0.0',port));occupied.listen()
                failed=command('enable');assert not failed['running'] and failed['threads']==failed['core']==0 and failed['memory_live']==0
            started=command('enable');assert started['running'] and started['threads']==started['core']==1 and started['devices']==0 and started['memory_live']>32768
            with ftplib.FTP() as bad:
                bad.connect('127.0.0.1',port,timeout=5)
                try:bad.login('wiixplorer','wrong-password')
                except ftplib.error_perm:pass
                else:raise AssertionError('bad password accepted')
                try:bad.nlst()
                except ftplib.error_perm:pass
                else:raise AssertionError('unauthenticated LIST allowed')
                try:bad.login('anonymous','any')
                except ftplib.error_perm:pass
                else:raise AssertionError('anonymous default enabled')
            ftp=connect()
            try:ftp.sendcmd('USER wrong-user')
            except ftplib.error_perm:pass
            else:raise AssertionError('bad username accepted')
            try:ftp.sendcmd('SIZE /sd/preserve')
            except ftplib.error_perm:pass
            else:raise AssertionError('USER failure retained authentication')
            ftp.login('wiixplorer','private-test-password');listing=ftp.nlst();assert set(('sd','usb1','nand')) <= set(listing),listing
            payload=bytes(range(256))*256
            for dev in ('sd','usb1'):
                ftp.storbinary('STOR /'+dev+'/fixture',io.BytesIO(payload))
                lines=[];ftp.retrlines('LIST /'+dev,lines.append);assert any('fixture' in x for x in lines),lines
                result=bytearray();ftp.retrbinary('RETR /'+dev+'/fixture',result.extend);assert result==payload
                ftp.storbinary('APPE /'+dev+'/fixture',io.BytesIO(b'append'))
                result=bytearray();ftp.retrbinary('RETR /'+dev+'/fixture',result.extend);assert result==payload+b'append'
                ftp.storbinary('STOR /'+dev+'/fixture',io.BytesIO(b'resume'),rest=7)
                result=bytearray();ftp.retrbinary('RETR /'+dev+'/fixture',result.extend);assert result[:13]==payload[:7]+b'resume'
                ftp.storbinary('STOR /'+dev+'/empty',io.BytesIO(b''));assert ftp.size('/'+dev+'/empty')==0
            for cmd in ('STOR /nand/secret','DELE /nand/secret','MKD /nand/new','PORT 1,2,3,4,1,1','PORT 127,0,0,1,0,0','PORT 127;0;0;1;1;1'):
                try:ftp.sendcmd(cmd)
                except ftplib.error_perm:pass
                else:raise AssertionError('unsafe operation accepted: '+cmd)
            command('hide_nand');assert 'nand' not in ftp.nlst()
            try:ftp.size('/nand/secret')
            except ftplib.error_perm:pass
            else:raise AssertionError('hidden NAND still exposed')
            idle=connect();time.sleep(3)
            try:idle.voidcmd('NOOP')
            except (EOFError,OSError,ftplib.Error):pass
            else:raise AssertionError('idle client survived timeout')
            idle.close();ftp.close()
            # Four live sessions, including an unfinished staged upload.
            clients=[connect() for _ in range(4)]
            data=clients[0].transfercmd('STOR /sd/preserve');data.sendall(b'partial');time.sleep(.05)
            stopped=command('disable');assert not stopped['running'] and stopped['threads']==stopped['core']==0 and stopped['memory_live']==0
            time.sleep(.15);assert command('status')==stopped;refused()
            assert (tmp/'sd:/preserve').read_bytes()==b'old destination'
            assert not list((tmp/'sd:').glob('*.wx-transfer-*'))
            for client in clients:
                try:assert client.sock.recv(1)==b''
                except ConnectionResetError:pass
                client.close()
            data.close()
            assert command('enable')['running']
            ftp=connect();assert 'sd' in ftp.nlst();ftp.close();command('disable')
            command('anon');command('enable');anon=connect('anonymous','ignored')
            assert 'sd' in anon.nlst()
            try:anon.storbinary('STOR /sd/anonymous',io.BytesIO(b'no'))
            except ftplib.error_perm:pass
            else:raise AssertionError('anonymous upload allowed')
            anon.close();command('disable')
            proc.stdin.write('exit\n');proc.stdin.flush();assert proc.wait(timeout=5)==0
            logs=(tmp/'log').read_text();assert 'private-test-password' not in logs and 'wrong-password' not in logs,logs
            assert 'ERROR: AddressSanitizer' not in logs and 'runtime error:' not in logs,logs
        except BaseException:
            print("Server exit",proc.poll(),"log:",(tmp/'log').read_text(),flush=True)
            raise
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
print('ftpsrv: disabled has no arena/thread/polls/enumeration; SD/USB LIST/RETR/STOR, authentication, timeout, shutdown, staged abort and re-enable passed')
