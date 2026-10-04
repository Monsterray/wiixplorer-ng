#!/usr/bin/env python3
"""Optional end-to-end ZIP checks against the project's pinned minizip sources.
Run make deps first. Fault-injection adapter checks always run in archives.py.
"""
import importlib.util,os,subprocess,tempfile,zipfile,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('archive_checks',ROOT/'tests/archives.py')
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
scope=vars(fixtures)
source=ROOT/'.deps/work/zip/source'
if not source.exists():
    print('Pinned ZIP codec checks skipped: run make deps to fetch sources')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='wx-zip-codec-') as tmp:
    p=Path(tmp)
    for name in ('good.zip','crc.zip','truncated.zip','unsafe.zip','link.zip','empty.zip'):
        with zipfile.ZipFile(p/name,'w',compression=zipfile.ZIP_STORED) as z:
            if name=='unsafe.zip':z.writestr('../escape','bad')
            elif name=='link.zip':
                info=zipfile.ZipInfo('link');info.create_system=3;info.external_attr=0o120777<<16;z.writestr(info,'../outside')
            elif name!='empty.zip':
                z.writestr('file',b'hello'*25000);z.writestr('empty/','');z.writestr('zero','')
    data=(p/'crc.zip').read_bytes();offset=30+struct.unpack_from('<H',data,26)[0]+struct.unpack_from('<H',data,28)[0]
    bad=bytearray(data);bad[offset]^=1;(p/'crc.zip').write_bytes(bad)
    # Keep a valid central directory but corrupt the local header; member open must fail.
    bad=bytearray(data);bad[0:4]=b'BAD!';(p/'truncated.zip').write_bytes(bad)
    (p/'short.zip').write_bytes(data[:len(data)//2])
    code=scope['common']+scope['stripped']('source/ArchiveOperations/ArchiveStruct.h')
    code+='\n#include "ArchiveOperations/ArchiveSafety.h"\n'+scope['stripped']('source/ArchiveOperations/ArchiveSafety.cpp')
    code+='\n#include "zip.h"\n#include "unzip.h"\n'+scope['stripped']('source/ArchiveOperations/ZipFile.h')+scope['stripped']('source/ArchiveOperations/ZipFile.cpp')
    code+=scope['helpers'].split('vector<u8> u8archive()')[0]
    code+=r'''
int main(){
 mkdir("out",0700);
 {ZipFile z("good.zip");assert(z.ExtractAll("out")==1);assert(get("out/file").size()==125000&&exists("out/empty")&&get("out/zero").empty());}
 for(const char *name:{"crc.zip","truncated.zip"}){put("out/file","original");ZipFile z(name);assert(z.ExtractFile(0,"out",true)<0);assert(get("out/file")=="original");}
 for(const char *name:{"unsafe.zip","link.zip","short.zip"}){ZipFile z(name);assert(z.GetItemCount()==0&&z.ExtractAll("out")<0);}
 {ZipFile z("empty.zip");assert(z.ExtractAll("out")==1);}
 mkdir("tree",0700);mkdir("tree/empty",0700);mkdir("tree/sub",0700);put("tree/sub/file","new");
 {ZipFile z("created.zip",ZipFile::CREATE);assert(z.AddDirectory("tree","root",6)==1);}
 {ZipFile z("created.zip");assert(z.GetItemCount()==4&&z.ExtractAll("out")==1);assert(get("out/root/sub/file")=="new");}
 {ZipFile z("created.zip",ZipFile::APPEND);assert(z.AddFile("tree/sub/file","added",6)==1);}
 {ZipFile z("created.zip");assert(z.GetItemCount()==5&&z.ExtractAll("out")==1&&get("out/added")=="new");}
 put("existing.zip","original");{ZipFile z("existing.zip",ZipFile::CREATE);canceled=true;assert(z.AddDirectory("tree","root",6)<0);canceled=false;}assert(get("existing.zip")=="original");
 return 0;
}
'''
    (p/'test.cpp').write_text(code)
    objects=[]
    for name in ('ioapi','unzip','zip'):
        obj=p/(name+'.o');objects.append(str(obj))
        subprocess.run([os.environ.get('CC','cc'),'-O1','-g','-fsanitize=address,undefined','-I'+str(source),'-c',str(source/(name+'.c')),'-o',str(obj)],check=True)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-O1','-g','-fsanitize=address,undefined','-I'+str(ROOT/'source'),'-I'+str(source),str(p/'test.cpp'),*objects,'-lz','-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],cwd=p,check=True,timeout=30)
    with zipfile.ZipFile(p/'created.zip') as z:
        assert sorted(z.namelist())==['added','root/','root/empty/','root/sub/','root/sub/file']
print('Pinned minizip: real CRC corruption, truncated/local-header failure, empty entries, exact directory tree and cancellation passed')
