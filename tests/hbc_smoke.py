#!/usr/bin/env python3
"""Ensure hardware smoke restores SD files on success and on transfer failure."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
client=r'''
import atexit,os
ENOENT=2
class HBCError(Exception):
 def __init__(self,code): self.code=code
base='sd:/apps/WiiXplorer/'
original={base+'WiiXplorer.cfg':b'personal settings',base+'WiiXplorer_Controls.cfg':b'personal controls',base+'probes.csv':b'old probes'}
if os.environ.get('ABSENT_ORIGINAL'):original={}
files=dict(original)
directories={'sd:/apps'} if os.environ.get('ABSENT_ORIGINAL') else {'sd:/apps','sd:/apps/WiiXplorer'}
original_dirs=set(directories)
agent=False
checks=0
csv=b'window,group,level,count,timed_count,total_us,max_us,value\n0,cpu,3,1,0,0,0,0\n'
def status(address):
 global checks
 checks+=1
 return {'agent':agent,'app':'WiiXplorer NG' if agent else 'HBC'}
def send(address,path,args):
 global agent
 if os.environ.get('STORAGE_TEST'):
  assert args[0]=='--smoke-frames=36000' and args[1].startswith('--storage-bench=usb1:/wiixplorer-copy-')
  assert args[2].startswith('--storage-report=sd:/wiixplorer-copy-')
  directory=args[2].split('=',1)[1];directories.add(directory)
  rows=['operation,buffer_bytes,repeat,bytes,microseconds,verified']
  for op,block in [('read',262144),('write',262144),('copy',131072),('copy',262144)]:
   for repeat in range(3):rows.append(f'{op},{block},{repeat},8388608,1000000,1')
  files[directory+'/storage-benchmark.csv']=('\n'.join(rows)+'\n').encode()
  files[directory+'/storage-complete']=b'1'
  files[directory+'/storage-metadata.csv']=b'device,filesystem\nusb1,FAT32\n'
 elif os.environ.get('MEMORY_TEST'):
  assert args[0]=='--smoke-frames=36000' and args[1].startswith('--memory-bench=sd:/wiixplorer-copy-')
  directory=args[1].split('=',1)[1];directories.add(directory)
  rows=['operation,source,destination,block_bytes,repeat,bytes,ticks_us,verified']
  groups=[('memcpy',src,dst,262144) for src in ('MEM1','MEM2') for dst in ('MEM1','MEM2')]
  groups += [('crc32_cached',src,'CPU',262144) for src in ('MEM1','MEM2')]
  groups += [('read32_hot',src,'CPU',8192) for src in ('MEM1','MEM2','LC')]
  groups += [('write32_hot','CPU',dst,8192) for dst in ('MEM1','MEM2','LC')]
  groups += [('dma_load',src,'LC',8192) for src in ('MEM1','MEM2')]
  groups += [('dma_store','LC',dst,8192) for dst in ('MEM1','MEM2')]
  for op,src,dst,block in groups:
   for repeat in range(3):rows.append(f'{op},{src},{dst},{block},{repeat},8388608,100000,1')
  files[directory+'/memory-benchmark.csv']=('\n'.join(rows)+'\n').encode()
  files[directory+'/memory-complete']=b'1'
  files[directory+'/memory-capacity.csv']=b'bank,physical_bytes\nMEM1,25165824\nMEM2,67108864\nLC,16384\n'
 else:assert args==['--smoke-frames=3600']
 assert b'DeleteTempPath = 0' in files[base+'WiiXplorer.cfg']
 agent=True
 files[base+'WiiXplorer_Controls.cfg']=b'controls saved by app'
 files[base+'probes.csv']=csv
 # Remove the waits; they are unnecessary in a deterministic protocol stub.
 import time
 time.sleep=lambda _:None
 time.monotonic=lambda:0

def foreign_app_check(address): pass
def screen(address):return 640,480,b'picture'
def yuyv_png(*args):return b'png'
def send_keys(*args):pass
def put_file(address,path,data): files[path]=data
def get_file(address,path):
 if os.environ.get('FAIL_TRANSFER') and 'wiixplorer-test-agent' in path: raise RuntimeError('transfer failure')
 if path not in files: raise HBCError(ENOENT)
 return files[path]
def file_request(address,op,path):
 if op=='L':
  if not path.endswith('/'):raise HBCError(ENOENT)
  if path.rstrip('/') not in directories:raise HBCError(ENOENT)
  return b'[]'
 if op=='M':directories.add(path);return b''
 if op=='D':
  if path in directories:
   assert not any(name.startswith(path+'/') for name in files)
   directories.remove(path);return b''
  if path not in files:raise HBCError(ENOENT)
  del files[path]
  return b''
 raise RuntimeError(op)
def request(address,header):
 global agent
 assert header==b'HBCX';agent=False;return b''
def hbc_wait(*args):assert not agent;return 'test HBC'
def exit_app(*args):
 global agent
 agent=False
@atexit.register
def validate():
 assert checks>=2 and not agent
 assert files==original and directories==original_dirs,(files,directories)
 print('SD originals restored')
'''
with tempfile.TemporaryDirectory(prefix='wiixplorer-bench-check-') as tmp:
    root=Path(tmp);(root/'scripts').mkdir();(root/'.deps/prefix/bin').mkdir(parents=True)
    (root/'scripts/hbc-smoke.py').write_text((ROOT/'scripts/hbc-smoke.py').read_text())
    (root/'.deps/prefix/bin/hbc.py').write_text(client)
    build=root/'build/debug';build.mkdir(parents=True)
    for name in ('boot.dol','boot.elf','boot.map','probe-config.h'): (build/name).write_bytes(b'test')
    (build/'build-info.json').write_text(json.dumps({'config':'debug'}))
    for failure, absent, storage, memory in ((False,False,False,False),(True,False,False,False),(False,True,False,False),(True,True,False,False),(False,False,True,False),(False,False,False,True)):
        env=dict(os.environ,WII_BENCH_JOB_START='1',WII_BENCH_IP='lease-only-test')
        if failure:env['FAIL_TRANSFER']='1'
        if absent:env['ABSENT_ORIGINAL']='1'
        if storage:env['STORAGE_TEST']='1'
        if memory:env['MEMORY_TEST']='1'
        args=['python3',str(root/'scripts/hbc-smoke.py'),'--hardware']
        if storage:args+=['--storage-device','usb1']
        if memory:args+=['--memory-bench']
        result=subprocess.run(args,env=env,capture_output=True,text=True)
        assert result.returncode==int(failure),result.stdout+result.stderr
        assert 'SD originals restored' in result.stdout,result.stdout+result.stderr
print('Hardware smoke: existing/absent SD files restored after success and transfer failure')
