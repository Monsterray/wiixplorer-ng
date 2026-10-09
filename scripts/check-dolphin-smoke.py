#!/usr/bin/env python3
"""Require guest teardown and valid probe output, not merely a successful launch."""
import argparse
import csv
import json
from pathlib import Path
import sys
from diagnose import collect

p = argparse.ArgumentParser()
p.add_argument('profile', type=Path)
p.add_argument('--probes', type=Path, help='extracted CSV for raw-SD runs')
p.add_argument('--max-log-mib', type=int, default=64)
a = p.parse_args()
if not 1 <= a.max_log_mib <= 1024: p.error("Log budget must be 1..1024 MiB")
profile = a.profile
try:
    info = json.loads((profile/'artifacts/build-info.json').read_text())
    if info['config'] != 'debug': raise ValueError('Smoke validation requires a debug build')
    evidence = collect(profile, a.max_log_mib * 1024 * 1024)
    if evidence['artifact_errors']: raise ValueError(evidence['artifact_errors'][0])
    if evidence['log']['verdict'] != 'clean_shutdown':
        raise ValueError('Dolphin validation failed: '+evidence['log']['verdict']+' '+(evidence['log']['first_fault'] or ''))
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
