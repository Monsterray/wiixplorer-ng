#!/usr/bin/env python3
"""Fixture faults remain failures; only owned profiles are cleaned up."""
import contextlib
import io
import json
from pathlib import Path
import runpy
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
main = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/dolphin-loader-repro.py'))['main']
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root/'build').mkdir()
    (root/'tests/fixtures').mkdir(parents=True)
    (root/'tests/fixtures/dolphin_loader_exit.c').write_text('fixture')
    commands = []
    profiles = []
    def run(command, **kwargs):
        commands.append(command)
        if command[0].endswith('elf2dol'):
            Path(command[-1]).write_bytes(b'frozen DOL')
            Path(command[-2]).write_bytes(b'frozen ELF')
        return SimpleNamespace(returncode=0)
    def prepare(command, **kwargs):
        p = root/('build/dolphin.test'+str(len(profiles)))
        profiles.append(p); p.mkdir()
        (p/'launch-command.json').write_text(json.dumps(['dolphin', '-e', 'old.dol', '-u', str(p)]))
        return 'Dolphin profile, frozen build, and logs: '+str(p)+'\n'
    reports = [dict(verdict='guest_fault', core_shutdown=True),
               dict(verdict='missing_app_cleanup', core_shutdown=True)]
    with patch.dict(main.__globals__, ROOT=root), patch('sys.argv', ['repro', '--repeat', '1']), \
         patch('subprocess.run', side_effect=run), patch('subprocess.check_output', side_effect=prepare), \
         patch.dict(main.__globals__, scan_log=lambda *args: reports.pop(0)), contextlib.redirect_stdout(io.StringIO()):
        assert main() == 1
    result = json.loads(next((root/'build').glob('loader-repro-*/result.json')).read_text())
    assert [r['passed'] for r in result] == [False, True]
    assert [r['core'] for r in result] == ['jit', 'interpreter']
    assert len({r['dol_sha256'] for r in result}) == 1
    stops = [c for c in commands if '--stop' in c]
    assert [c[-1] for c in stops] == [str(p) for p in profiles]
    assert all('wiibench' not in str(c) for c in commands)
print('Loader reproducer: frozen fixture, fault rejection, CPU modes and owned cleanup passed')

# Exercise the real shell argument/launch construction without launching Dolphin.
import os
import shutil
import subprocess
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root/'scripts').mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[1]/'scripts/dolphin.sh', root/'scripts/dolphin.sh')
    (root/'build/debug').mkdir(parents=True)
    (root/'build/debug/boot.dol').write_bytes(b'fixture')
    (root/'.deps/prefix').mkdir(parents=True)
    (root/'.deps/prefix/hbc-agent.json').write_text('{}')
    for options, core, debugger in (([], 1, False), (['--gdb-port', '55020'], 1, True),
                                     (['--cpu-core', 'interpreter'], 0, False)):
        output = subprocess.check_output(['bash', str(root/'scripts/dolphin.sh'), '--build',
            'debug', '--prepare-only', *options], cwd=root,
            env={**os.environ, 'DOLPHIN_WIIMOTE_CONFIG':str(root/'unused')}, text=True)
        p = Path(output.strip().split('Dolphin profile, frozen build, and logs: ',1)[1])
        command = json.loads((p/'launch-command.json').read_text())
        assert 'Dolphin.Core.CPUCore='+str(core) in command
        assert ('-d' in command) == debugger
        assert ('-b' in command) != debugger
print('Dolphin prepare: real GDB debugger mode and explicit CPU selection passed')
