/****************************************************************************
 * Copyright (C) 2013 Dimok
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
#include "UpdateTask.h"
#include "Controls/Application.h"
#include "Prompts/PromptWindow.h"

UpdateTask::UpdateTask(bool updateApp, bool updateLang, bool silent)
	: Task(tr("Checking for updates")), bAutoDelete(false),
	  bUpdateApp(updateApp), bUpdateLang(updateLang), bSilent(silent)
{
}

UpdateTask::~UpdateTask()
{
}

void UpdateTask::Execute(void)
{
	TaskBegin(this);
	if(!bSilent)
		ThrowMsg(tr("Updates disabled"), tr("The legacy update service is no longer supported. Install updates manually."));
	TaskEnd(this);
	if(bAutoDelete)
		Application::Instance()->PushForDelete(this);
}

// The Google Code service used unsigned HTTP downloads. Keep the public
// entry points inert until a maintained, authenticated updater replaces it.
int UpdateTask::CheckForUpdate(void) { return -1; }
int UpdateTask::DownloadApp(const char *) { return -1; }
bool UpdateTask::DownloadMetaXml(void) { return false; }
bool UpdateTask::DownloadIconPNG(void) { return false; }
bool UpdateTask::UpdateLanguageFiles(void) { return false; }
