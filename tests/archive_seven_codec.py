#!/usr/bin/env python3
"""Optional real pinned 7z SDK adapter regression under ASan/UBSan."""
from pathlib import Path
import importlib.util,os,shutil,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1];source=ROOT/'.deps/work/sevenzip/source'
if not source.exists() or not shutil.which('7z'):
    print('Real 7z codec checks skipped: requires make deps and a host 7z command')
    raise SystemExit(0)
spec=importlib.util.spec_from_file_location('archive_checks',ROOT/'tests/archives.py');f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
with tempfile.TemporaryDirectory(prefix='wx-seven-codec-') as tmp:
    p=Path(tmp);(p/'aaa').write_bytes(b'A'*8192);(p/'payload').write_bytes(b'fixture'*30000);(p/'empty').mkdir();(p/'zero').touch()
    subprocess.run(['7z','a','-t7z','-ms=on','-mx=5','good.7z','aaa','payload','empty','zero'],cwd=p,check=True,stdout=subprocess.DEVNULL)
    data=bytearray((p/'good.7z').read_bytes());data[32]^=1;(p/'corrupt.7z').write_bytes(data)
    (p/'payload').write_bytes(b'Z'*(17*1024*1024));subprocess.run(['7z','a','-t7z','-ms=on','-mx=5','budget.7z','payload'],cwd=p,check=True,stdout=subprocess.DEVNULL)
    code=f.common+f.stripped('source/ArchiveOperations/ArchiveStruct.h')+'\n#include "ArchiveOperations/ArchiveSafety.h"\n'+f.stripped('source/ArchiveOperations/ArchiveSafety.cpp')
    code+='\nextern "C" {\n#include "7z.h"\n#include "7zFile.h"\n#include "7zAlloc.h"\n#include "7zCrc.h"\n}\n'
    code+='struct wString:std::wstring {std::string toUTF8(){std::string s;for(auto c:*this){assert(c<128);s.push_back(c);}return s;}};\n'
    code+=f.stripped('source/ArchiveOperations/7ZipFile.h')+f.stripped('source/ArchiveOperations/7ZipFile.cpp')+f.helpers.split('vector<u8> u8archive()')[0]
    code+=r'''
int main(){mkdir("out",0700);string expected;for(int i=0;i<30000;++i)expected+="fixture";
 {SzFile a("good.7z");assert(a.GetItemCount()==4&&!a.GetFileStruct(4)&&!a.GetFileStruct(-1));assert(a.ExtractAll("out")==1);assert(get("out/payload")==expected);assert(exists("out/empty")&&get("out/zero").empty());}
 for(const char *file:{"corrupt.7z","budget.7z"}){put("out/payload","original");SzFile a(file);assert(a.GetItemCount()>0&&a.ExtractAll("out")<0);assert(get("out/payload")=="original");}
 return 0;}
'''
    (p/'test.cpp').write_text(code);objects=[]
    names=('7zIn','7zBuf','7zBuf2','7zCrc','7zCrcOpt','7zDec','7zFile','7zStream','Bcj2','Bra','Bra86','BraIA64','CpuArch','LzmaDec','Lzma2Dec')
    for name in names:
        obj=p/(name+'.o');objects.append(str(obj))
        subprocess.run([os.environ.get('CC','cc'),'-D_7ZIP_ST','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(source),'-c',str(source/(name+'.c')),'-o',str(obj)],check=True)
    subprocess.run([os.environ.get('CXX','c++'),'-D_7ZIP_ST','-std=c++11','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(ROOT/'source'),'-I'+str(source),str(p/'test.cpp'),*objects,'-lz','-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],cwd=p,check=True,timeout=60)
print('Real pinned 7z SDK: solid nonzero member offsets, empty entries, indices, corruption preservation and decoder budget passed')
