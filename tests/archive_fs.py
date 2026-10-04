#!/usr/bin/env python3
"""Check production no-follow callbacks from dependency patches with host shims."""
from pathlib import Path
import os,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
def callback(library,prefix):
    patch=(ROOT/'scripts/patches'/f'{library}.patch').read_text()
    lines=[];collect=False
    for line in patch.splitlines():
        if line.startswith('+int '+prefix+'_lstat_r'):collect=True
        if collect and line.startswith('--- '):break
        if collect and line.startswith('+') and not line.startswith('+++'):lines.append(line[1:])
    return '\n'.join(lines)
code=r'''
#include <sys/stat.h>
#include <cstring>
#include <cassert>
#include <cerrno>
struct _reent{int _errno;};struct ntfs_vd{};struct ext2_vd{};struct ntfs_inode{unsigned flags;};struct ext2_inode_t{};
const unsigned FILE_ATTR_REPARSE_POINT=1024;
bool failStat=false,nofollow=false;int locks=0;
ntfs_vd *ntfsGetVolume(const char*){static ntfs_vd v;return &v;}ext2_vd *ext2GetVolume(const char*){static ext2_vd v;return &v;}
void ntfs_log_trace(const char*,...){}void ext2_log_trace(const char*,...){}
void ntfsLock(ntfs_vd*){++locks;}void ntfsUnlock(ntfs_vd*){--locks;}
void ext2Lock(ext2_vd*){++locks;}void ext2Unlock(ext2_vd*){--locks;}
ntfs_inode *ntfsParseEntry(ntfs_vd*,const char*,int depth){assert(depth==-1);nofollow=true;static ntfs_inode i{FILE_ATTR_REPARSE_POINT};return &i;}
ext2_inode_t *ext2OpenEntryNoFollow(ext2_vd*,const char*){nofollow=true;static ext2_inode_t i;return &i;}
int ntfsStat(ntfs_vd*,ntfs_inode*,struct stat*st){st->st_mode=S_IFDIR;return failStat ? -1 : 0;}
int ext2Stat(ext2_vd*,ext2_inode_t*,struct stat*st){st->st_mode=S_IFLNK;return failStat ? -1 : 0;}
void ntfsCloseEntry(ntfs_vd*,ntfs_inode*){}void ext2CloseEntry(ext2_vd*,ext2_inode_t*){}
'''
code+=callback('ntfs','ntfs')+callback('ext2fs','ext2')
code+=r'''
int main(){_reent r{};struct stat st{};
 assert(ntfs_lstat_r(&r,"usb1:/link",&st)==0&&S_ISLNK(st.st_mode)&&nofollow&&locks==0);
 nofollow=false;assert(ext2_lstat_r(&r,"usb1:/link",&st)==0&&S_ISLNK(st.st_mode)&&nofollow&&locks==0);
 failStat=true;assert(ntfs_lstat_r(&r,"usb1:/file",&st)<0&&locks==0);assert(ext2_lstat_r(&r,"usb1:/file",&st)<0&&locks==0);
}
'''
with tempfile.TemporaryDirectory(prefix='wx-archive-fs-') as tmp:
    p=Path(tmp);(p/'test.cpp').write_text(code)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-fsanitize=address,undefined',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True,timeout=10)
print('Archive filesystem callbacks: no-follow resolution, reparse/link rejection, stat errors and lock cleanup passed')
