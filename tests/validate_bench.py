#!/usr/bin/env python3
"""The hardware queue must never receive an emulator-failing build."""
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
from unittest.mock import patch

main = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/validate-bench.py'))['main']
for failure in (None, 'dolphin-check', 'hardware', 'stop', 'ftp', 'timeout'):
    with tempfile.TemporaryDirectory(prefix='wx-validation-') as directory:
        root = Path(directory)
        profile = root/'build/dolphin.fixture'
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            if command[0] == 'bash':
                profile.mkdir()
                (profile/'artifacts').mkdir()
                (profile/'artifacts/boot.dol').write_bytes(b'fixed-build')
                (profile/"launch-command.json").write_text(json.dumps(["fixture-dolphin","-e",str(profile/"artifacts/boot.dol"),"-u",str(profile)]))
                kwargs['stdout'].write('Dolphin profile, frozen build, and logs: '+str(profile)+'\n')
            if failure=='hardware' and 'wait' in command:
                hardware=root/'build/wii.fixture';hardware.mkdir()
                (hardware/'scenario-stage.json').write_text(json.dumps({'stage':'ftp-list'}))
                kwargs['stdout'].write('HBC smoke artifacts: '+str(hardware)+'\n')
            if (failure=='dolphin-check' and 'scripts/check-dolphin-smoke.py' in command or
                failure=='hardware' and 'wait' in command or
                failure=='stop' and '--stop' in command):
                raise subprocess.CalledProcessError(1, command)
            if failure=='timeout' and 'scripts/hbc-smoke.py' in command:
                raise subprocess.TimeoutExpired(command,30)
            if 'add' in command:
                kwargs['stdout'].write('fixture-job\n')
        with patch.dict(main.__globals__, ROOT=root), patch('sys.argv',
                ['validate-bench.py', 'ftp' if failure=='ftp' else 'media', '--hardware', '--skip-build', '--cpu-core', 'jit']), patch('subprocess.run', side_effect=run):
            try: main()
            except SystemExit as error: assert error.code==1 and failure in ('dolphin-check','hardware','stop','timeout')
            else: assert failure in (None,'ftp')
        launch=next(command for command in commands if 'fixture-dolphin' in command)
        assert launch[-4:] == ['-e',str(profile/'artifacts/boot.dol'),'-u',str(profile)]
        prepare=next(i for i,c in enumerate(commands) if '--prepare-only' in c)
        port=next(i for i,c in enumerate(commands) if 'scripts/hbc-port.py' in c)
        assert prepare<port<commands.index(launch)
        assert commands[prepare][commands[prepare].index('--cpu-core')+1] == 'jit'
        queued = [command for command in commands if 'add' in command]
        assert bool(queued) == (failure not in ('dolphin-check','stop','timeout'))
        if queued:
            assert queued[0][-1] == str(profile/'artifacts')
            assert commands.index(queued[0]) > next(i for i,c in enumerate(commands) if 'scripts/check-dolphin-smoke.py' in c)
            assert any('wait' in command and 'fixture-job' in command for command in commands)
        assert commands[-1][-2:] == ['--force-stop' if failure=='stop' else '--stop', str(profile)]
        result = json.loads(next((root/'build').glob('validation-*/result.json')).read_text())
        assert result['passed'] == (failure in (None,'ftp'))
        assert result['cpu_core'] == 'jit'
        assert ('cleanup_error' in result)==(failure=='stop')
        assert result['steps'] and all('seconds' in step for step in result['steps'])
        assert (next((root/'build').glob('validation-*/diagnostics.json'))).exists()
        if failure=='hardware':assert result['hardware_stage']=='ftp-list'
        if failure in ('dolphin-check','hardware','stop','timeout'):assert result['failure_stage']==('dolphin-smoke' if failure=='timeout' else failure)
print('Validation runner: frozen artifact, Dolphin gate, queue wait and owned cleanup passed')
# Repeats remain on one artifact; reject a changed DOL before another launch/lease.
for change in (False, True):
    with tempfile.TemporaryDirectory(prefix='wx-repeat-') as directory:
        root=Path(directory); commands=[]; profiles=[]
        def run(command, **kwargs):
            commands.append(command)
            if command[0]=='bash':
                profile=root/('build/dolphin.fixture'+str(len(profiles)));profiles.append(profile)
                (profile/'artifacts').mkdir(parents=True)
                (profile/'artifacts/boot.dol').write_bytes(b'changed' if change and len(profiles)>1 else b'fixed')
                (profile/'launch-command.json').write_text(json.dumps(['fixture-dolphin','-u',str(profile)]))
                kwargs['stdout'].write('Dolphin profile, frozen build, and logs: '+str(profile)+'\n')
        with patch.dict(main.__globals__, ROOT=root), patch('sys.argv',['validate-bench.py','exit','--skip-build','--repeat','2']),patch('subprocess.run',side_effect=run):
            try:main()
            except SystemExit as error:assert change and error.code==1
            else:assert not change
        assert len(profiles)==2
        assert sum('fixture-dolphin' in c for c in commands)==(1 if change else 2)
        assert all('--capture' not in c for c in commands)
        assert any('--exit-only' in c for c in commands)
        results=[json.loads(p.read_text()) for p in sorted((root/'build').glob('validation-*/result.json'))]
        if change:assert any(r.get('failure_stage')=='artifact' for r in results)
print('Validation repeats: minimal exit, frozen DOL stability and no launch after changed artifact passed')

with patch('sys.argv', ['validate-bench.py', 'ftp', '--hardware', '--cpu-core', 'interpreter']), patch('subprocess.run') as runner:
    try: main()
    except SystemExit as error: assert error.code == 2
    else: raise AssertionError('Interpreter diagnostic must not queue hardware')
    runner.assert_not_called()
print('Interpreter-only hardware gate rejected before build/launch/queue')
