#!/usr/bin/env python3
"""Run the production task queue against deterministic host thread/LWP adapters."""
from pathlib import Path
import os
import subprocess
import tempfile
root = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory() as folder:
    p = Path(folder)
    (p/'malloc.h').write_text('#include <cstdlib>\n')
    (p/'ogc').mkdir()
    (p/'Diagnostics').mkdir()
    (p/'gccore.h').write_text('#pragma once\n#include <cstdint>\n')
    (p/'Diagnostics/Probes.h').write_text('#define WX_SCOPE(g) ((void)0)\n#define WX_PROBE(g,l,v) ((void)0)\n')
    (p/'CMutex.h').write_text((root/'source/Controls/CMutex.h').read_text())
    (p/'ogc/mutex.h').write_text('''#pragma once
#include <mutex>
#include <thread>
#include <cassert>
struct Mutex {std::recursive_mutex m;std::thread::id owner;unsigned depth=0;};
using mutex_t=Mutex*;
#define LWP_MUTEX_NULL nullptr
inline int LWP_MutexInit(mutex_t *m,bool){*m=new Mutex;return 0;}
inline int LWP_MutexLock(mutex_t m){m->m.lock();m->owner=std::this_thread::get_id();++m->depth;return 0;}
inline int LWP_MutexUnlock(mutex_t m){assert(m->owner==std::this_thread::get_id());if(!--m->depth)m->owner={};m->m.unlock();return 0;}
inline int LWP_MutexDestroy(mutex_t m){assert(!m->depth);delete m;return 0;}
inline int LWP_MutexTryLock(mutex_t m){return LWP_MutexLock(m);}
''')
    (p/'ogc/semaphore.h').write_text('''#pragma once
#include <mutex>
#include <condition_variable>
struct Sem { std::mutex m; std::condition_variable cv; bool pending=false; };
using sem_t=Sem*;
inline int LWP_SemInit(sem_t *s,int,int){*s=new Sem;return 0;}
inline int LWP_SemPost(sem_t s){std::lock_guard<std::mutex> l(s->m);s->pending=true;s->cv.notify_one();return 0;}
inline int LWP_SemWait(sem_t s){std::unique_lock<std::mutex> l(s->m);s->cv.wait(l,[&]{return s->pending;});s->pending=false;return 0;}
inline int LWP_SemDestroy(sem_t s){delete s;return 0;}
''')
    (p/'CThread.h').write_text('''#pragma once
#include <thread>
#include <mutex>
#include <condition_variable>
#include <atomic>
extern std::atomic<bool> enter_worker;
class CThread {
 std::thread t; std::mutex m; std::condition_variable cv; bool awake=false;
public:
 CThread(int,int){}
 virtual ~CThread(){shutdownThread();}
 virtual void executeThread()=0;
 void startThread(){t=std::thread([this]{while(!enter_worker.load()) std::this_thread::yield(); executeThread();});}
 void resumeThread(){std::lock_guard<std::mutex> l(m);awake=true;cv.notify_one();}
 void suspendThread(){std::unique_lock<std::mutex> l(m);awake=false;cv.wait(l,[this]{return awake;});}
 void shutdownThread(){if(t.joinable()){resumeThread();t.join();}}
};
''')
    for file in ('ThreadedTaskHandler.cpp','ThreadedTaskHandler.hpp'):
        (p/file).write_text((root/'source/Controls'/file).read_text())
    (p/'test.cpp').write_text('''#include "ThreadedTaskHandler.hpp"
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <iostream>
std::atomic<bool> enter_worker(false);
struct Task:ThreadedTask { std::atomic<int>& completed; Task(std::atomic<int>&c):completed(c){} void Execute(){++completed;} };
int main(){
 std::atomic<int> completed(0); Task task(completed);
 auto *queue=ThreadedTaskHandler::Instance();
 // Queue before the worker enters its loop: a suspend/resume implementation loses this wakeup.
 queue->AddTask(&task); enter_worker=true;
 auto limit=std::chrono::steady_clock::now()+std::chrono::seconds(2);
 while(completed<1 && std::chrono::steady_clock::now()<limit) std::this_thread::yield();
 if(completed!=1){std::cerr<<"lost wakeup for queued task\\n";std::_Exit(1);}
 std::thread a([&]{for(int i=0;i<1000;++i)queue->AddTask(&task);});
 std::thread b([&]{for(int i=0;i<1000;++i)queue->AddTask(&task);});a.join();b.join();
 limit=std::chrono::steady_clock::now()+std::chrono::seconds(2);
 while(completed<2001 && std::chrono::steady_clock::now()<limit) std::this_thread::yield();
 if(completed!=2001){std::cerr<<"concurrent task queue lost work\\n";std::_Exit(1);}
 ThreadedTaskHandler::DestroyInstance();
 std::cout<<"task queue: retained wakeup, 2001 tasks, idle shutdown passed\\n";
}
''')
    subprocess.run([os.environ.get('CXX','c++'), '-std=c++11', '-pthread', '-fsanitize=address,undefined', '-I'+str(p), str(p/'ThreadedTaskHandler.cpp'), str(p/'test.cpp'), '-o', str(p/'test')], check=True)
    subprocess.run([str(p/'test')], check=True, timeout=8)
