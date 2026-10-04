#!/usr/bin/env python3
"""Exercise the production native runner against pinned minizip on a host."""
import importlib.util,os,subprocess,tempfile,zipfile,struct,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('archive_checks',ROOT/'tests/archives.py')
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
source=ROOT/'.deps/work/zip/source'
if not source.exists():
    print('Native archive harness codec check skipped: run make deps')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='wx-native-archive-') as tmp:
    p=Path(tmp);root=p/'sd:/wiixplorer-archive-host';root.mkdir(parents=True)
    payload=b'fixture'*30000
    with zipfile.ZipFile(root/'good.zip','w',compression=zipfile.ZIP_STORED) as z:
        z.writestr('payload',payload);z.writestr('zero','');z.writestr('empty/','')
    data=bytearray((root/'good.zip').read_bytes());data[30+struct.unpack_from('<H',data,26)[0]]^=1;(root/'crc.zip').write_bytes(data)
    manifest=f'good.zip 1 3 payload {len(payload)} {zlib.crc32(payload):08x}\ncrc.zip 0 3 payload 0 0\n'
    (root/'manifest').write_text(manifest)
    code=f.common+f.stripped('source/ArchiveOperations/ArchiveStruct.h')+'\n#include "ArchiveOperations/ArchiveSafety.h"\n'+f.stripped('source/ArchiveOperations/ArchiveSafety.cpp')
    code+='\n#include "zip.h"\n#include "unzip.h"\n'+f.stripped('source/ArchiveOperations/ZipFile.h')+f.stripped('source/ArchiveOperations/ZipFile.cpp')
    code+=r'''
#include <chrono>
#define WX_DEBUG_BUILD 1
u64 gettime(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
u64 ticks_to_microsecs(u64 t){return t/1000;}
class ArchiveHandle {ZipFile z;public:ArchiveHandle(const char*p):z(p){}ArchiveFileStruct *GetFileStruct(int i){return z.GetFileStruct(i);}unsigned GetItemCount(){return z.GetItemCount();}int ExtractAll(const char*p){return z.ExtractAll(p);}};
'''+f.stripped('source/Diagnostics/ArchiveBench.cpp')+r'''
int main(){RunArchiveValidation(NULL,NULL);RunArchiveValidation("nand:/wiixplorer-archive-host",NULL);RunArchiveValidation("sd:/ordinary",NULL);RunArchiveValidation("sd:/wiixplorer-archive-host",getenv("USB_ROOT"));return 0;}
'''
    (p/'test.cpp').write_text(code);objects=[]
    for name in ('ioapi','unzip','zip'):
        obj=p/(name+'.o');objects.append(str(obj))
        subprocess.run([os.environ.get('CC','cc'),'-O1','-g','-fsanitize=address,undefined','-I'+str(source),'-c',str(source/(name+'.c')),'-o',str(obj)],check=True,stdout=subprocess.DEVNULL)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-O1','-g','-fsanitize=address,undefined','-I'+str(ROOT/'source'),'-I'+str(source),str(p/'test.cpp'),*objects,'-lz','-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],cwd=p,check=True,timeout=30)
    assert (root/'archive-complete').read_bytes()==b'1'
    assert (root/'out-crc.zip/payload').read_bytes()==b'original'
    import csv
    rows=list(csv.DictReader((root/'archive-results.csv').read_text().splitlines()))
    assert len(rows)==3 and all(r['verified']=='1' for r in rows)
    with zipfile.ZipFile(root/'created.zip') as z:
        assert sorted(z.namelist())==['packed/','packed/empty/','packed/sub/','packed/sub/payload']
    # Exercise the actual USB staging/cleanup path with a host devoptab directory.
    (p/'usb1:').mkdir()
    subprocess.run([str(p/'test')],cwd=p,env=dict(os.environ,USB_ROOT='usb1:/wiixplorer-archive-host'),check=True,timeout=30)
    assert (root/'archive-complete').read_bytes()==b'1'
    assert not (p/'usb1:/wiixplorer-archive-host').exists()
    # Malformed manifest must fail without publication or a success marker.
    (root/'manifest').write_text('../escape 1 1 payload 1 0\n')
    subprocess.run([str(p/'test')],cwd=p,check=True,timeout=30)
    assert (root/'archive-complete').read_bytes()==b'0'
print('Native archive runner: real ZIP extraction, failed CRC preservation, exact packing, report completion and manifest guards passed')
