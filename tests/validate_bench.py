#!/usr/bin/env python3
"""The hardware queue must never receive an emulator-failing build."""
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
from unittest.mock import patch

main = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/validate-bench.py'))['main']
for failure in (None, 'dolphin-check', 'hardware', 'stop'):
    with tempfile.TemporaryDirectory(prefix='wx-validation-') as directory:
        root = Path(directory)
        profile = root/'build/dolphin.fixture'
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            if command[0] == 'bash':
                profile.mkdir()
                (profile/"launch-command.json").write_text(json.dumps(["fixture-dolphin","-e",str(profile/"artifacts/boot.dol"),"-u",str(profile)]))
                kwargs['stdout'].write('Dolphin profile, frozen build, and logs: '+str(profile)+'\n')
            if (failure=='dolphin-check' and 'scripts/check-dolphin-smoke.py' in command or
                failure=='hardware' and 'wait' in command or
                failure=='stop' and '--stop' in command):
                raise subprocess.CalledProcessError(1, command)
            if 'add' in command:
                kwargs['stdout'].write('fixture-job\n')
        with patch.dict(main.__globals__, ROOT=root), patch('sys.argv',
                ['validate-bench.py', 'media', '--hardware', '--skip-build']), patch('subprocess.run', side_effect=run):
            try: main()
            except subprocess.CalledProcessError: assert failure in ('dolphin-check','hardware')
            else: assert failure in (None,'stop')
        launch=next(command for command in commands if 'fixture-dolphin' in command)
        assert launch[-4:] == ['-e',str(profile/'artifacts/boot.dol'),'-u',str(profile)]
        prepare=next(i for i,c in enumerate(commands) if '--prepare-only' in c)
        port=next(i for i,c in enumerate(commands) if 'scripts/hbc-port.py' in c)
        assert prepare<port<commands.index(launch)
        queued = [command for command in commands if 'add' in command]
        assert bool(queued) == (failure!='dolphin-check')
        if queued:
            assert queued[0][-1] == str(profile/'artifacts')
            assert commands.index(queued[0]) > next(i for i,c in enumerate(commands) if 'scripts/check-dolphin-smoke.py' in c)
            assert any('wait' in command and 'fixture-job' in command for command in commands)
        assert commands[-1][-2:] == ['--stop', str(profile)]
        result = json.loads(next((root/'build').glob('validation-*/result.json')).read_text())
        assert result['passed'] == (failure is None)
        assert ('cleanup_error' in result)==(failure=='stop')
print('Validation runner: frozen artifact, Dolphin gate, queue wait and owned cleanup passed')
