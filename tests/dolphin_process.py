#!/usr/bin/env python3
"""Process ownership checks: a launcher's arguments must never make it a target."""
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
module = runpy.run_path(str(Path(__file__).resolve().parent.parent/'scripts/dolphin-process.py'))
processes = module['processes']
with patch('subprocess.run', side_effect=[
    SimpleNamespace(stdout='101 /usr/bin/python3\n102 /Applications/Dolphin.app/Contents/MacOS/Dolphin\n103 /Applications/Dolphin.app/Contents/MacOS/Dolphin\n104 /Applications/Dolphin.app/Contents/MacOS/Dolphin\n'),
    SimpleNamespace(stdout='101 python3 runner.py /project/build/dolphin.A open -a /Applications/Dolphin.app\n102 /Applications/Dolphin.app/Contents/MacOS/Dolphin -u /project/build/dolphin.A\n103 /Applications/Dolphin.app/Contents/MacOS/Dolphin -u /other/project\n104 /Applications/Dolphin.app/Contents/MacOS/Dolphin -e /project/build/dolphin.A/boot.dol -u /personal/profile\n')]):
    assert processes('/project/build/dolphin.A') == [102]
with patch.dict(processes.__globals__, windows=True), patch('subprocess.run', return_value=SimpleNamespace(stdout='[{"ProcessId":102,"CommandLine":"Dolphin.exe -u C:\\\\project\\\\build\\\\dolphin.A"},{"ProcessId":103,"CommandLine":"Dolphin.exe -u C:\\\\other\\\\project"}]')):
    assert processes('C:\\project\\build\\dolphin.A') == [102]
print('Dolphin ownership: launcher excluded, other profiles excluded, Windows match passed')
