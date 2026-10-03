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
#include "ProcessTask.h"
#include "Controls/Application.h"
#include <errno.h>
#include <stdint.h>
#include "Controls/Taskbar.h"
#include "Prompts/ProgressWindow.h"
#include "FileOperations/fileops.h"

ProcessTask::ProcessTask(const std::string &title, const ItemMarker *p, const std::string &dest)
	: Task(title), destPath(dest)
{
	TaskType = Task::PROCESS;
	CopyFiles = 0;
	PlanEntries = PlanBytes = 0;
	CopySize = 0;
	Process = *p;

	ShowNormal.connect(this, &ProcessTask::ShowProgressWindow);
}

void ProcessTask::ShowProgressWindow(Task *task UNUSED, int param UNUSED)
{
	ProgressWindow::Instance()->OpenWindow();
}

bool ProcessTask::ReservePlanPath(const string &path)
{
    // Charge conservatively for path capacity, list nodes and ItemList owners.
    if (path.size() >= 1024 || PlanEntries >= MaxPlanEntries) return false;
    u32 charge = 128 + 2*(path.size()+1);
    if (charge > MaxPlanBytes-PlanBytes) return false;
    PlanBytes += charge;
    ++PlanEntries;
    return true;
}

int ProcessTask::GetItemList(list<ItemList> &fileLists, bool listDirs)
{
    fileLists.clear();
    PlanEntries = PlanBytes = CopyFiles = 0;
    CopySize = 0;
    int ret = 0;
    if (Process.GetItemcount() > (int)MaxPlanEntries) ret = -1;
    for (int i=0; ret == 0 && i<Process.GetItemcount(); ++i) {
        if (ProgressWindow::Instance()->IsCanceled() || Application::isClosing()) {
            ret = PROGRESS_CANCELED; break;
        }
        string source = Process.GetItemPath(i);
        if (!ReservePlanPath(source)) { ret = -1; break; }
        fileLists.resize(fileLists.size()+1);
        ItemList &entry = fileLists.back();
        entry.basepath = source;
        while (!entry.basepath.empty() && entry.basepath.back() == '/')
            entry.basepath.erase(entry.basepath.size()-1);
        size_t pos = entry.basepath.rfind('/');
        if (pos == string::npos) { ret = -1; break; }
        entry.basepath.erase(pos+1);
        if (Process.IsItemDir(i)) {
            string path = Process.GetItemName(i);
            ret = ReadDirectory(path, entry, listDirs);
        } else {
            string path = source.substr(pos+1);
            struct stat st;
            if (!ReservePlanPath(path) || destPath.size()+path.size()+1 > 992 ||
                stat(source.c_str(), &st) != 0 || !S_ISREG(st.st_mode) ||
                st.st_size < 0 || (u64)st.st_size > UINT64_MAX-CopySize) {
                ret = -1; break;
            }
            entry.files.push_back(path);
            CopySize += st.st_size;
            ++CopyFiles;
        }
        ShowProgress(0, CopySize);
    }
    if (ret < 0) {
        // A partial plan must never be consumed as a completed selection.
        fileLists.clear();
        CopySize = CopyFiles = 0;
    }
    return ret;
}

int ProcessTask::ReadDirectory(string &path, ItemList &fileList, bool listDirs, unsigned depth)
{
    if (ProgressWindow::Instance()->IsCanceled() || Application::isClosing()) return PROGRESS_CANCELED;
    if (depth >= MaxPlanDepth || !ReservePlanPath(path) || fileList.basepath.size()+path.size() >= 1024 ||
        destPath.size()+path.size()+1 > 992) return -1;
    DIR *dir = opendir((fileList.basepath+path).c_str());
    if (!dir) return -1;
    int ret = 0;
    list<string> subdirectories;
    for (;;) {
        if (ProgressWindow::Instance()->IsCanceled() || Application::isClosing()) {
            ret = PROGRESS_CANCELED; break;
        }
        errno = 0;
        struct dirent *de = readdir(dir);
        if (!de) { if (errno) ret = -1; break; }
        if (!strcmp(de->d_name,".") || !strcmp(de->d_name,"..")) continue;
        string child = path+"/"+de->d_name;
        if (fileList.basepath.size()+child.size() >= 1024 ||
            destPath.size()+child.size()+1 > 992) { ret = -1; break; }
        struct stat st;
        if (stat((fileList.basepath+child).c_str(), &st) != 0) { ret = -1; break; }
        if (S_ISDIR(st.st_mode)) {
            if (!ReservePlanPath(child)) { ret = -1; break; }
            subdirectories.push_back(child);
        } else {
            if (!S_ISREG(st.st_mode) || st.st_size < 0 ||
                (u64)st.st_size > UINT64_MAX-CopySize || !ReservePlanPath(child)) {
                ret = -1; break;
            }
            fileList.files.push_back(child);
            CopySize += st.st_size;
            ++CopyFiles;
        }
        ShowProgress(0, CopySize);
    }
    if (closedir(dir) != 0 && ret == 0) ret = -1;
    // FTP/NFS directory streams own backend buffers. Keep only one open,
    // rather than retaining a directory stream at every recursion level.
    for (list<string>::iterator child=subdirectories.begin(); ret == 0 && child != subdirectories.end(); ++child)
        ret = ReadDirectory(*child, fileList, listDirs, depth+1);
    if (ret == 0 && listDirs) fileList.dirs.push_back(path);
    return ret;
}
