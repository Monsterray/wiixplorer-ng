#!/usr/bin/env python3
"""Exercise CThread when its entry runs before its handle is published."""
from pathlib import Path
import os,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='wx-thread-start-') as directory:
    tmp=Path(directory)
    (tmp/'gccore.h').write_text(r'''
#pragma once
#include <thread>
#include <mutex>
#include <condition_variable>
#include <cassert>
#include <chrono>
using u8=unsigned char;using lwp_t=int;
#define LWP_THREAD_NULL 0
static std::mutex lock;static std::condition_variable cv;
static bool suspended=false,finished=false;static std::thread worker;
static thread_local lwp_t self=0;
inline lwp_t LWP_GetSelf(){return self;}
inline int LWP_SuspendThread(lwp_t id){assert(id==1);std::unique_lock<std::mutex> guard(lock);suspended=true;cv.notify_all();cv.wait(guard,[]{return !suspended;});return 0;}
inline int LWP_CreateThread(lwp_t *id,void *(*fn)(void*),void *arg,void*,int,int){
 worker=std::thread([=]{self=1;fn(arg);std::lock_guard<std::mutex> guard(lock);finished=true;cv.notify_all();});
 std::unique_lock<std::mutex> guard(lock);cv.wait(guard,[]{return suspended||finished;});*id=1;return 0;}
inline bool LWP_ThreadIsSuspended(lwp_t){std::lock_guard<std::mutex> guard(lock);return suspended;}
inline int LWP_ResumeThread(lwp_t){std::lock_guard<std::mutex> guard(lock);suspended=false;cv.notify_all();return 0;}
inline int LWP_JoinThread(lwp_t,void*){worker.join();return 0;}
inline int LWP_SetThreadPriority(lwp_t,int){return 0;}
''')
    (tmp/'malloc.h').write_text('#include <cstdlib>\ninline void *memalign(size_t alignment,size_t size){void *p=nullptr;return posix_memalign(&p,alignment,size)?nullptr:p;}\n')
    (tmp/'test.cpp').write_text(r'''
#include "Controls/CThread.h"
class Task:public CThread{
 bool ready=false;
 public:Task():CThread(){ready=true;startThread();}
 ~Task(){shutdownThread();}
 void executeThread(){assert(ready);}
};
int main(){Task task;}
''')
    binary=tmp/'test'
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-pthread','-fsanitize=address,undefined','-I'+str(tmp),'-I'+str(ROOT/'source'),str(tmp/'test.cpp'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)
print('Thread startup: entry-before-handle publication waits for derived construction')
