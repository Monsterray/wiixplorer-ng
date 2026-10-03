#!/usr/bin/env python3
"""Restore SD configuration from an interrupted, leased hbc-smoke run."""
import argparse
import importlib.util
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('profile',type=Path)
parser.add_argument('--wait',type=int,default=0,help='wait up to 900 seconds for the app safety timer to return to HBC')
a=parser.parse_args()
if not 0 <= a.wait <= 900: parser.error("Wait must be 0..900 seconds")
profile=a.profile.resolve()
if profile.parent!=ROOT/'build' or not profile.name.startswith('wii.'):
    parser.error('Use an hbc-smoke artifact directory in this project')
if not os.environ.get('WII_BENCH_JOB_START') or not os.environ.get('WII_BENCH_IP'):
    parser.error('Restoration must run inside the shared Wii bench lease')
spec=importlib.util.spec_from_file_location('hbc_client',ROOT/'.deps/prefix/bin/hbc.py')
hbc=importlib.util.module_from_spec(spec);spec.loader.exec_module(hbc)
address=os.environ['WII_BENCH_IP']
if a.wait: hbc.hbc_wait(address,a.wait)
if hbc.status(address).get('agent'): raise RuntimeError('Return the Wii to HBC before restoring')
for name in ('WiiXplorer.cfg','WiiXplorer_Controls.cfg','probes.csv'):
    saved=profile/('original-'+name)
    remote='sd:/apps/WiiXplorer/'+name
    if saved.exists(): hbc.put_file(address,remote,saved.read_bytes())
    else:
        try: hbc.file_request(address,'D',remote)
        except hbc.HBCError as error:
            if error.code!=hbc.ENOENT: raise
print('Original SD configuration, controls and probes restored')
