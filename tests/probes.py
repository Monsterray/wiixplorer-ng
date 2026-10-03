#!/usr/bin/env python3
"""Verify disabled groups/levels don't evaluate probe payloads or call timers."""
from pathlib import Path
import os
import subprocess
import tempfile
header = Path(__file__).resolve().parent.parent/'source/Diagnostics/Probes.h'
code = '#include "'+str(header)+'"\n' + r'''
#include <cassert>
int calls=0, clocks=0, values=0;
extern "C" uint64_t wx_probe_begin(){++clocks;return 1;}
extern "C" void wx_probe_record(unsigned,unsigned,uint64_t,uint32_t){++calls;}
int main(){
 {
  WX_SCOPE(CPU);
  WX_PROBE(CPU,1,++values);
  WX_PROBE(GPU,3,++values);
 }
 { WX_SCOPE(NETWORK); WX_PROBE(NETWORK,1,++values); }
 assert(calls == (WX_PROBE_LEVEL>=1)+(WX_PROBE_LEVEL>=2)+(WX_PROBE_LEVEL>=3));
 assert(clocks == (WX_PROBE_LEVEL>=2));
 assert(values == (WX_PROBE_LEVEL>=1)+(WX_PROBE_LEVEL>=3));
}
'''
with tempfile.TemporaryDirectory() as folder:
    folder = Path(folder)
    source = folder/'probes.cpp'
    source.write_text(code)
    for level in range(4):
        binary=folder/f'probes-{level}'
        flags=[f'-DWX_PROBE_LEVEL={level}', '-DWX_PROBE_CPU=1','-DWX_PROBE_GPU=1',
               '-DWX_PROBE_THREADS=0','-DWX_PROBE_IO=0','-DWX_PROBE_NETWORK=0']
        subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-Wall','-Wextra',*flags,str(source),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
print('Probes: levels 0–3, disabled groups/payloads/timers passed')
