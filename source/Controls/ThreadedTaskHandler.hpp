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
#ifndef THREADED_TASK_HPP_
#define THREADED_TASK_HPP_

#include <gccore.h>
#include <queue>
#include <atomic>
#include <ogc/semaphore.h>
#include "CMutex.h"
#include "CThread.h"

class ThreadedTask
{
public:
	ThreadedTask() {}
	virtual ~ThreadedTask() {}
	virtual void Execute(void) = 0;
};

class ThreadedTaskHandler : public CThread
{
public:
	static ThreadedTaskHandler * Instance() { if(!instance) instance = new ThreadedTaskHandler(); return instance; };
	static void DestroyInstance() { delete instance; instance = NULL; };

	// Tasks remain owned by the caller (some callers queue stack objects).
	void AddTask(ThreadedTask *Task);

private:
	ThreadedTaskHandler();
	virtual ~ThreadedTaskHandler();

	void executeThread(void);

	static ThreadedTaskHandler *instance;
	std::atomic_bool ExitRequested;
	sem_t wake;
	CMutex queueMutex;
	std::queue<ThreadedTask *> TaskList;
};

#endif
