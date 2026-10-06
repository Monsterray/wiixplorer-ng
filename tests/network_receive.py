#!/usr/bin/env python3
"""Exercise the production WiiLoad prompt/clipboard path under sanitizers."""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
source=(root/'source/network/netreceive.cpp').read_text()
source=source[source.index('void IncommingConnection('):]
code=r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cstdio>
using u8=uint8_t;using u64=uint64_t;
struct ItemStruct{char *itempath;u64 itemsize;bool isdir;int itemindex;};
unsigned added=0,booted=0,copied=0;bool accepted=true,received=true;
const char *tr(const char *s){return s;}
int WindowPrompt(const char*,const char*,const char*,const char*){return accepted;}
void CopyHomebrewMemory(u8*,unsigned,unsigned n){assert(n==64);++copied;}
void BootHomebrew(){++booted;}
struct Clipboard{
 static Clipboard *Instance(){static Clipboard c;return &c;}
 void AddItem(const ItemStruct *p){assert(p && !strcmp(p->itempath,"WiiLoad") && p->itemsize==64 && !p->isdir && p->itemindex==0);++added;}
};
struct NetReceiver{
 unsigned freed=0,closed=0;
 const char *GetIncommingIP(){return "127.0.0.1";}
 const char *GetFilename(){return "test.dol";}
 unsigned GetFilesize(){return 64;}
 const u8 *ReceiveData(){static u8 buffer[64];return received ? buffer : nullptr;}
 void FreeData(){++freed;}void CloseConnection(){++closed;}
};
'''+source+r'''
int main(){
 NetReceiver r;IncommingConnection(r);assert(added==1 && copied==1 && booted==1 && r.freed==1 && r.closed==1);
 accepted=false;IncommingConnection(r);assert(added==1 && r.freed==2 && r.closed==2);
 accepted=true;received=false;IncommingConnection(r);assert(added==1 && r.freed==3 && r.closed==3);
}
'''
with tempfile.TemporaryDirectory(prefix='wx-receive-') as tmp:
 p=Path(tmp);(p/'test.cpp').write_text(code)
 subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-g','-O1','-fsanitize=address,undefined',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=30)
print('WiiLoad receive: initialized clipboard metadata, accept/reject/failure cleanup passed')
