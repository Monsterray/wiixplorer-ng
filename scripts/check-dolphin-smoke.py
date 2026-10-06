#!/usr/bin/env python3
"""Require guest teardown and valid probe output, not merely a successful launch."""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
import sys

p = argparse.ArgumentParser()
p.add_argument('profile', type=Path)
p.add_argument('--probes', type=Path, help='extracted CSV for raw-SD runs')
a = p.parse_args()
profile = a.profile
try:
    info = json.loads((profile/'artifacts/build-info.json').read_text())
    if info['config'] != 'debug': raise ValueError('Smoke validation requires a debug build')
    for line in (profile/'artifacts/SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        if Path(name).name != name: raise ValueError('Invalid artifact name')
        if hashlib.sha256((profile/'artifacts'/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Frozen artifact hash mismatch: '+name)
    log = (profile/'Logs/dolphin.log').read_text(errors='replace')
    faults=re.findall(r'^.*(?:\b(?:DSI|ISI|machine check|program|alignment|FPU unavailable) exception\b|exception \((?:DSI|ISI)\)|invalid (?:read|write) (?:from|to)|panic alert|stack dump|backtrace:).*$',log,re.IGNORECASE|re.MULTILINE)
    if faults: raise ValueError('Guest exception/error recorded: '+faults[0].strip())
    if 'WiiXplorer: shutdown cleanup completed'  not in log:
        raise ValueError('Guest did not report completed teardown')
    if 'Shutdown complete ----' not in log:
        raise ValueError('Dolphin did not report completed core shutdown')
    if info['probe_level']:
        path = a.probes or profile/'Load/WiiSDSync/apps/WiiXplorer/probes.csv'
        with path.open(newline='') as f:
            rows = list(csv.DictReader(f))
        if not rows: raise ValueError('Probe CSV is empty')
        for row in rows:
            if None in row or any(value is None for value in row.values()):
                raise ValueError('Incomplete probe CSV row')
            for key in ('window','level','count','timed_count','total_us','max_us','value'):
                int(row[key])
            if row['group'] in ('cpu','gpu') and row['level']=='3' and int(row['value']):
                raise ValueError('CPU/GPU integrity probe failed')
        memory=profile/'Load/WiiSDSync/apps/WiiXplorer/memory-probes.csv'
        if memory.exists():
            with memory.open(newline='') as f: memory_rows=list(csv.DictReader(f))
            last={}
            for row in memory_rows:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError('Incomplete memory probe row')
                if row['kind']=='owner':
                    if int(row['accounting_errors']): raise ValueError('Memory accounting mismatch')
                    last[(row['owner'],row['bank'])]=row
                if row['kind']=='snapshot' and int(row['integrity_errors']):
                    raise ValueError('Memory snapshot integrity failure')
            if any(int(row['live_bytes']) for row in last.values()):
                raise ValueError('Tracked operation buffers remain live after teardown')
            (profile/'memory-probes.csv').write_bytes(memory.read_bytes())
        smoke = profile/'Load/WiiSDSync/apps/WiiXplorer/smoke-frames.txt'
        if 'cpu' in info['probe_groups']:
            updates = sum(int(r['count']) for r in rows if r['group']=='cpu' and r['level']=='1')
            if updates<=0: raise ValueError('No GUI updates')
            remote=profile/'hbc-smoke.json'
            intentional_exit=remote.exists() and json.loads(remote.read_text()).get('passed') is True
            if smoke.exists() and not intentional_exit and updates<int(smoke.read_text()):
                raise ValueError('Insufficient GUI updates')
except (OSError, ValueError, KeyError) as error:
    sys.exit(str(error))
print('Smoke passed: frozen build verified, guest/core teardown completed, probe output valid')
