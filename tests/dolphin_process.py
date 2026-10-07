#!/usr/bin/env python3
"""Process ownership checks: a launcher's arguments must never make it a target."""
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import errno
module = runpy.run_path(str(Path(__file__).resolve().parent.parent/'scripts/dolphin-process.py'))
processes = module['processes']
with patch('subprocess.run', side_effect=[
    SimpleNamespace(stdout='101 /usr/bin/python3\n102 /Applications/Dolphin.app/Contents/MacOS/Dolphin\n103 /Applications/Dolphin.app/Contents/MacOS/Dolphin\n104 /Applications/Dolphin.app/Contents/MacOS/Dolphin\n'),
    SimpleNamespace(stdout='101 python3 runner.py /project/build/dolphin.A open -a /Applications/Dolphin.app\n102 /Applications/Dolphin.app/Contents/MacOS/Dolphin -u /project/build/dolphin.A\n103 /Applications/Dolphin.app/Contents/MacOS/Dolphin -u /other/project\n104 /Applications/Dolphin.app/Contents/MacOS/Dolphin -e /project/build/dolphin.A/boot.dol -u /personal/profile\n')]):
    assert processes('/project/build/dolphin.A') == [102]
with patch.dict(processes.__globals__, windows=True), patch('subprocess.run', return_value=SimpleNamespace(stdout='[{"ProcessId":102,"CommandLine":"Dolphin.exe -u C:\\\\project\\\\build\\\\dolphin.A"},{"ProcessId":103,"CommandLine":"Dolphin.exe -u C:\\\\other\\\\project"}]')):
    assert processes('C:\\project\\build\\dolphin.A') == [102]
print('Dolphin ownership: launcher excluded, other profiles excluded, Windows match passed')

check_port=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/hbc-port.py'))['check_port']
for occupied in (False,True):
    route=MagicMock();route.__enter__.return_value=route;route.getsockname.return_value=('192.168.1.2',1234)
    check=MagicMock();check.__enter__.return_value=check
    if occupied:check.bind.side_effect=OSError(errno.EADDRINUSE,'occupied')
    with patch('socket.socket',side_effect=[route,check]):
        try:check_port()
        except RuntimeError:assert occupied
        else:assert not occupied
    check.bind.assert_called_once_with(('192.168.1.2',4299))
    check.listen.assert_not_called();check.connect.assert_not_called()
print('HBC port preflight: collision rejected without listener or foreign-agent connection')
