/****************************************************************************
 * Copyright (C) 2011 Dimok
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
#include "PackTask.h"
#include "Controls/Application.h"
#include "Controls/Taskbar.h"
#include "Prompts/PromptWindow.h"
#include "Prompts/ProgressWindow.h"
#include "FileOperations/fileops.h"
#include "ArchiveOperations/ArchiveSafety.h"

PackTask::PackTask(const ItemMarker *p, const std::string &dest, ArchiveHandle *a, int comp)
	: ProcessTask(tr("Compressing item(s):"), p, dest), archive(a), compression(comp)
{
	if(archive)
		archive->AddReference();
}

PackTask::~PackTask()
{
	if(archive && archive->RemoveReference() <= 0)
		delete archive;
}

static inline void RemoveDoubleSlash(char *str)
{
	if(!str) return;
	int count = 0;
	const char *ptr = str;
	while(*ptr != 0)
	{
		if(*ptr == '/' && ptr[1] == '/') {
			ptr++;
			continue;
		}
		str[count] = *ptr;
		ptr++;
		count++;
	}

	str[count] = 0;
}

void PackTask::Execute(void)
{
	TaskBegin(this);

	// No items to process
	if(!archive || Process.GetItemcount() == 0)
	{
		TaskEnd(this);
		return;
	}

    // ZIP's walker owns traversal. Do not build/discard an entire recursive
    // transfer plan just to estimate progress before scanning it again.
    if(ProgressWindow::Instance()->IsRunning()) ProgressWindow::Instance()->SetTitle(this->getTitle().c_str());
    else StartProgress(this->getTitle().c_str());
    s64 total=0;
    for(int i=0;i<Process.GetItemcount();++i) {
        if(Process.IsItemDir(i) || Process.GetItemSize(i)>(u64)INT64_MAX-(u64)total) { total=-1; break; }
        total+=Process.GetItemSize(i);
    }
    ProgressWindow::Instance()->SetCompleteValues(0,total);

	int result = Process.GetItemcount()>WX_ARCHIVE_ITEMS ? -1 : 0;
	char destpath[MAXPATHLEN];

	for(int i = 0; i < Process.GetItemcount() && result>=0; i++)
	{
		int ret;
        int joined;
		if(destPath.size() > 0)
			joined = snprintf(destpath, sizeof(destpath), "%s/%s", destPath.c_str(), Process.GetItemName(i));
		else
			joined = snprintf(destpath, sizeof(destpath), "%s", Process.GetItemName(i));

        if(joined<0 || (size_t)joined>=sizeof(destpath)) { result=-1; break; }
		RemoveDoubleSlash(destpath);

		if(Process.IsItemDir(i))
			ret = archive->AddDirectory(Process.GetItemPath(i), destpath, compression);
		else
			ret = archive->AddFile(Process.GetItemPath(i), destpath, compression);
		if(ret < 0) { result=ret; break; }

		if(wx_archive_cancelled())
		{
			result = PROGRESS_CANCELED;
			break;
		}

	}

    if(!archive->FinishWrite(result>=0 && !wx_archive_cancelled()) && result>=0) result=-1;
    if(wx_archive_cancelled()) result=PROGRESS_CANCELED;
	if(!Application::isClosing() && result != PROGRESS_CANCELED)
	{
		if(result == -30)
			ThrowMsg(tr("Error:"), tr("Pasting files is currently only supported on ZIP archives."));
		else if(result < 0)
			ThrowMsg(tr("Error:"), tr("Failed adding some item(s)."));
	}

	TaskEnd(this);
}
