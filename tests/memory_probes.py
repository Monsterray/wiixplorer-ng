#!/usr/bin/env python3
"""Check production memory counters, bounded snapshots and disabled payloads."""
from pathlib import Path
import csv
import os
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
code=r'''
#include <cassert>
#include <cstring>
#include <cstdio>
#include <sys/stat.h>
#include "Diagnostics/MemoryProbes.h"
bool failClose=false;unsigned closes=0;
int probeClose(FILE *f){++closes;int result=fclose(f);return failClose?EOF:result;}
#define fclose probeClose
#include "Diagnostics/MemoryProbes.cpp"
#undef fclose
extern "C" unsigned MEM2_freesize(){return 1024;}
extern "C" unsigned MEM2_heapsize(){return 2048;}
extern "C" unsigned MEM2_largestblock(){return 512;}
extern "C" bool MEM2_check(){return true;}
int main(){
 int evaluated=0;
 WX_MEMORY_ALLOC(NETWORK,WX_MEM_FTP_CORE,++evaluated,++evaluated);
 WX_MEMORY_FREE(NETWORK,WX_MEM_FTP_CORE,++evaluated,++evaluated);
 {WX_MEMORY_BUFFER(NETWORK,WX_MEM_FTP_STACK,(void*)(uintptr_t)++evaluated,++evaluated);}
 assert(evaluated==0); // NETWORK group off, including RAII payloads.
#if WX_PROBE_LEVEL > 0
 // Failed report open retains data for the next main-thread flush.
 wx_memory_record(WX_MEM_COPY,0x80000020,128,1);wx_memory_flush();assert(!window);
 mkdir("sd:",0700);mkdir("sd:/apps",0700);mkdir("sd:/apps/WiiXplorer",0700);
 wx_memory_record(WX_MEM_COPY,0x90000020,256,1);
 wx_memory_record(WX_MEM_COPY,0,512,1);
 wx_memory_record(WX_MEM_COPY,0x80000020,128,0);
 wx_memory_record(WX_MEM_COPY,0x90000020,256,0);
 wx_memory_record(WX_MEM_COPY,0x90000020,1,0); // Expose mismatched bookkeeping.
 assert(owners[WX_MEM_COPY][0].live==0 && owners[WX_MEM_COPY][1].live==0);
 for(unsigned i=0;i<12;++i)WX_MEMORY_SNAPSHOT("explicit_event");
#if WX_PROBE_LEVEL >= 2
 assert(count==8 && dropped==4);
 unsigned char stack[64];memset(stack,0xa5,sizeof(stack));memset(stack+48,0,16);
 wx_memory_stack(WX_MEM_FTP_STACK,stack,sizeof(stack));assert(stackPeaks[WX_MEM_FTP_STACK][0]==16);
#endif
 wx_memory_flush();assert(window==1 && count==0);
 unsigned before=written;wx_memory_flush();assert(window==1 && written==before);
 // Repeated lifetimes balance counters without a pointer registry.
 for(unsigned i=0;i<10000;++i){wx_memory_record(WX_MEM_ZIP_PACK,0x80000020,32,1);wx_memory_record(WX_MEM_ZIP_PACK,0x80000020,32,0);}
 assert(owners[WX_MEM_ZIP_PACK][0].live==0 && owners[WX_MEM_ZIP_PACK][0].peak==32);
 wx_memory_flush();assert(window==2);
 failClose=true;wx_memory_record(WX_MEM_COPY,0,1,1);wx_memory_flush();assert(outputFailed && window==2);
 unsigned beforeFailure=closes;wx_memory_record(WX_MEM_COPY,0,1,1);wx_memory_flush();assert(closes==beforeFailure);
#endif
}
'''
with tempfile.TemporaryDirectory(prefix='wx-memory-probes-') as temp:
 p=Path(temp);(p/'ogc').mkdir()
 (p/'malloc.h').write_text('struct mallinfo { unsigned uordblks,fordblks; };\ninline struct mallinfo mallinfo(){return {512,1024};}\n')
 (p/'ogc/irq.h').write_text('inline unsigned IRQ_Disable(){return 0;}\ninline void IRQ_Restore(unsigned){}\n')
 (p/'test.cpp').write_text(code)
 for level in range(4):
  run=p/str(level);run.mkdir()
  flags=[f'-DWX_PROBE_LEVEL={level}','-DWX_PROBE_CPU=1','-DWX_PROBE_IO=1','-DWX_PROBE_GPU=1','-DWX_PROBE_THREADS=1','-DWX_PROBE_NETWORK=0']
  subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-g','-fsanitize=address,undefined',*flags,'-I'+str(p),'-I'+str(ROOT/'source'),str(p/'test.cpp'),'-o',str(run/'test')],check=True)
  subprocess.run([str(run/'test')],cwd=run,check=True,timeout=30)
  report=run/'sd:/apps/WiiXplorer/memory-probes.csv'
  if not level: assert not report.exists();continue
  with report.open() as stream: rows=list(csv.DictReader(stream))
  assert rows and all(None not in row and all(v is not None for v in row.values()) for row in rows),rows
  owners=[r for r in rows if r['kind']=='owner' and r['owner']=='copy_io']
  assert {r['bank'] for r in owners}=={'MEM1','MEM2','unknown'}
  assert all(r['live_bytes']=='0' for r in owners)
  events=[r for r in rows if r['kind']=='snapshot']
  assert len(events)==(8 if level>=2 else 0)
  assert all(r['mem2_largest']=='512' and r['integrity_errors']=='0' and r['dropped_snapshots']=='4' for r in events)
print('Memory probes: levels 0–3, disabled payloads, owner peaks/failures, bounded event ring, idle suppression and CSV passed')
