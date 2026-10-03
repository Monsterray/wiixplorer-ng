/****************************************************************************
 * Copyright (C) 2010-2011 Dimok
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 ****************************************************************************/
#include "Diagnostics/Probes.h"
#include "ThreadedTaskHandler.hpp"

ThreadedTaskHandler * ThreadedTaskHandler::instance = NULL;

ThreadedTaskHandler::ThreadedTaskHandler()
	: CThread(80, 65*1024)
	, ExitRequested(false)
{
	LWP_SemInit(&wake, 0, 1);
	startThread();
}

ThreadedTaskHandler::~ThreadedTaskHandler()
{
    ExitRequested = true;
    LWP_SemPost(wake);
    shutdownThread(); // Join while the queue and derived vtable still exist.
    LWP_SemDestroy(wake);
}

void ThreadedTaskHandler::AddTask(ThreadedTask *task)
{
    queueMutex.lock();
    if (!ExitRequested) TaskList.push(task);
    queueMutex.unlock();
    LWP_SemPost(wake);
    WX_PROBE(THREADS, 1, 1);
}

void ThreadedTaskHandler::executeThread(void)
{
    while (!ExitRequested) {
        LWP_SemWait(wake);
        while (!ExitRequested) {
            queueMutex.lock();
            ThreadedTask *task = TaskList.empty() ? NULL : TaskList.front();
            if (task) TaskList.pop();
            WX_PROBE(THREADS, 3, TaskList.size());
            queueMutex.unlock();
            if (!task) break;
            WX_SCOPE(THREADS);
            task->Execute();
        }
    }
}
