#!/usr/bin/env python3
"""Optional production RAR adapter checks with the pinned legacy decoder."""
from pathlib import Path
import importlib.util,os,subprocess,tempfile,runpy,shutil
ROOT=Path(__file__).resolve().parents[1];source=ROOT/'.deps/work/unrar'
if not (source/'rar.hpp').exists() or not shutil.which('7z'):
    print('Real RAR codec checks skipped: requires make deps and a host 7z command')
    raise SystemExit(0)
spec=importlib.util.spec_from_file_location('archive_checks',ROOT/'tests/archives.py');f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
with tempfile.TemporaryDirectory(prefix='wx-rar-codec-') as tmp:
    p=Path(tmp);runpy.run_path(str(ROOT/'scripts/archive-fixtures.py'))['generate'](p/'fixtures')
    code=f.common+f.stripped('source/ArchiveOperations/ArchiveStruct.h')+'\n#include "ArchiveOperations/ArchiveSafety.h"\n'+f.stripped('source/ArchiveOperations/ArchiveSafety.cpp')
    code+='\n#include <cstdarg>\n#include <sys/param.h>\n#include "rar.hpp"\n'
    code+='#define UNUSED\nint WindowPrompt(const char*,const char*,const char*,const char*){return 0;}int OnScreenKeyboard(char*,int){return 0;}\n'
    rar_code=f.stripped('source/ArchiveOperations/RarFile.cpp')
    code+=f.stripped('source/ArchiveOperations/RarFile.h')+rar_code+f.stripped('source/ArchiveOperations/RarErrHnd.cpp')+f.helpers.split('vector<u8> u8archive()')[0]
    code+=r'''
int main(){mkdir("out",0700);
 for(const char*name:{"good.rar","normal.rar"}){string path=string("fixtures/")+name;RarFile a(path.c_str());assert(a.GetItemCount()==1&&!a.GetFileStruct(1)&&!a.GetFileStruct(-1));assert(a.ExtractAll("out")==1);}
 assert(get("out/payload").size()==135000&&get("out/LibarchiveAddingTest.html").size()==20111);
 put("out/LibarchiveAddingTest.html","original");{RarFile a("fixtures/best.rar");assert(a.GetItemCount()==1&&a.ExtractAll("out")<0&&get("out/LibarchiveAddingTest.html")=="original");} // PPM requests 25 MiB, exceeding the explicit decoder budget.
 put("out/payload","original");{RarFile a("fixtures/crc.rar");assert(a.ExtractAll("out")<0&&get("out/payload")=="original");}
 {RarFile a("fixtures/header.rar");assert(a.GetItemCount()==0&&a.ExtractAll("out")<0&&get("out/payload")=="original");}
 return 0;}
'''
    (p/'test.cpp').write_text(code);objects=[]
    names=('strlist strfn pathfn savepos smallfn file filefn filcreat archive arcread unicode system isnt crypt crc rawread encname resource match timefn rdwrfn consio options ulinks rarvm rijndael getbits sha1 extinfo extract volume list find unpack cmddata filestr recvol rs scantree').split()
    flags=['-DUNRAR','-DSILENT','-std=gnu++11','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(source)]
    for name in names:
        obj=p/(name+'.o');objects.append(str(obj))
        subprocess.run([os.environ.get('CXX','c++'),*flags,'-c',str(source/(name+'.cpp')),'-o',str(obj)],check=True)
    subprocess.run([os.environ.get('CXX','c++'),*flags,'-I'+str(ROOT/'source'),str(p/'test.cpp'),*objects,'-lz','-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],cwd=p,check=True,timeout=60)
print('Real pinned RAR: stored/normal codecs, indices, bad main-header/CRC preservation and PPM budget rejection passed')
