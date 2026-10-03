/****************************************************************************
 * Copyright (C) 2009-2011 Dimok
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
#ifndef _APPLICATION_H
#define _APPLICATION_H

#include <queue>
#include <atomic>
#include "GUI/gui_frame.h"
#include "GUI/gui_image.h"
#include "GUI/gui_button.h"
#include "Controls/WiiPointer.h"
#include "Controls/CMutex.h"

class ThreadedTask;

class Application : public GuiFrame, public sigslot::has_slots<>
{
	public:
		static Application * Instance() { if(!instance) instance = new Application(); return instance; }
		static void DestroyInstance() { delete instance; instance = NULL; }

		void init();
		void quit();
		void exec();
#if WX_DEBUG_BUILD
		void SetSmokeFrames(u32 frames) { smokeFrames = frames; }
#endif
		void show();
		void hide();
		void updateEvents();
		static void shutdownSystem() { bShutdown = true; }
		static void resetSystem() { bReset = true; }
		static bool isClosing() { return exitApplication; }
		static void closeRequest() { exitApplication = true; }

		void SetGrabPointer(int i);
		void ResetPointer(int i);

		void Append(GuiElement *e)
		{
			m_mutex.lock();
			GuiFrame::Append(e);
			m_mutex.unlock();
		}

		void PushForDelete(GuiElement *e);

		void SetGuiInputUpdate(bool b) { bGuiInputUpdate = b; }

		void SetUpdateOnly(GuiElement *e)
		{
			m_mutex.lock();
			UnsetUpdateOnly(e);
			updateOnlyElement.push_back(e);
			m_mutex.unlock();
		}

        void UnsetUpdateOnly(GuiElement *e)
        {
            m_mutex.lock();
            for (u32 i=0; i<updateOnlyElement.size();) {
                if (updateOnlyElement[i] == e) updateOnlyElement.erase(updateOnlyElement.begin()+i);
                else ++i;
            }
            m_mutex.unlock();
        }

		void addPostRenderTask(ThreadedTask *t)
		{
			m_mutex.lock();
			postUpdateTasks.push(t);
			m_mutex.unlock();
		}

		GXColor * GetBGColorPtr() { return bgImg->GetColorPtr(); }
	private:
		Application();
		virtual ~Application();
		void OnHomeButtonClick(GuiButton *sender, int pointer, const POINT &p);
		bool homePending = false;

		void ProcessDeleteQueue(void);
		void ProcessPostUpdateTasks(void);

		static Application *instance;
		static std::atomic_bool exitApplication;
		static std::atomic_bool bReset;
		static std::atomic_bool bShutdown;

		GuiImage *bgImg;
		WiiPointer *pointer[4];
		GuiButton *btnHome;
		GuiTrigger trigHome;
		std::vector<GuiElement *> updateOnlyElement;
		std::vector<GuiElement *> deleteList;
		std::queue<ThreadedTask *> postUpdateTasks;
		CMutex m_mutex;
		lwp_t renderThread;
#if WX_DEBUG_BUILD
		u32 smokeFrames;
#endif
		bool bGuiInputUpdate;
};

#endif //_APPLICATION_H
