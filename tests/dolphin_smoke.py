#!/usr/bin/env python3
"""Guest faults must fail even when teardown completes; remote exit is valid."""
from pathlib import Path
import hashlib,json,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp);(p/'artifacts').mkdir();(p/'Logs').mkdir();sd=p/'Load/WiiSDSync/apps/WiiXplorer';sd.mkdir(parents=True)
    data=json.dumps({'config':'debug','probe_level':3,'probe_groups':['cpu','gpu']}).encode()
    (p/'artifacts/build-info.json').write_bytes(data)
    (p/'artifacts/SHA256SUMS').write_text(hashlib.sha256(data).hexdigest()+'  build-info.json\n')
    okay='WiiXplorer: shutdown cleanup completed\nShutdown complete ----\n'
    (p/'Logs/dolphin.log').write_text(okay)
    def probes(count=600):
        (sd/'probes.csv').write_text('window,group,level,count,timed_count,total_us,max_us,value\n0,cpu,1,'+str(count)+',0,0,0,0\n0,gpu,3,1,0,0,0,0\n')
    def run():return subprocess.run(['python3',str(ROOT/'scripts/check-dolphin-smoke.py'),str(p)],capture_output=True,text=True)
    probes();assert run().returncode==0
    for fault in ('DSI exception at 0x80001234','Invalid read from 0x00000010, PC = 0x80001234','Exception (ISI) occurred','Machine check exception','PANIC ALERT: guest fault'):
        (p/'Logs/dolphin.log').write_text(fault+'\n'+okay)
        result=run();assert result.returncode!=0,'Undetected guest fault: '+fault
    (p/'Logs/dolphin.log').write_text(okay)
    (sd/'smoke-frames.txt').write_text('600\n');probes(10);assert run().returncode!=0
    (p/'hbc-smoke.json').write_text(json.dumps({'passed':True}));assert run().returncode==0
    probes(0);assert run().returncode!=0
print('Dolphin smoke: guest faults rejected, bounded timer and intentional remote exit distinguished')
