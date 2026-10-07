#!/usr/bin/env python3
"""Capture rebuilds preserve the existing helper unless changed inputs compile."""
from pathlib import Path
import runpy
import subprocess
import tempfile
from unittest.mock import patch

build=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/build-wii-capture.py'))['build']
with tempfile.TemporaryDirectory(prefix='wx-capture-build-') as temporary:
    root=Path(temporary);(root/'scripts').mkdir()
    source=root/'scripts/wii-capture.m';source.write_text('fixture')
    (root/'scripts/wii-capture.plist').write_text('privacy purpose')
    calls=[]
    def compile(command,**kwargs):
        if command[0]=='codesign': return
        calls.append(command)
        assert any('__info_plist' in arg for arg in command)
        Path(command[-1]).write_bytes(b'compiled helper')
    with patch.dict(build.__globals__,ROOT=root),patch('sys.platform','darwin'),patch('subprocess.run',side_effect=compile):
        build();executable=root/'build/tools/wii-capture';stamp=executable.with_suffix('.sha256')
        previous=executable.stat().st_mtime_ns
        build();assert len(calls)==1 and executable.stat().st_mtime_ns==previous
        original_stamp=stamp.read_bytes()
        source.write_text('changed fixture')
        with patch('subprocess.run',side_effect=subprocess.CalledProcessError(1,'clang')):
            try: build()
            except subprocess.CalledProcessError: pass
            else: raise AssertionError('Compiler failure must propagate')
        assert executable.read_bytes()==b'compiled helper' and stamp.read_bytes()==original_stamp
        build();assert len(calls)==2 and stamp.read_bytes()!=original_stamp
        assert not list(executable.parent.glob('capture-build-*'))
print('Capture build: unchanged identity, embedded privacy purpose, failed rebuild preservation and cleanup passed')
