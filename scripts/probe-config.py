#!/usr/bin/env python3
"""Generate a stable header so changing probe flags rebuilds affected objects."""
import pathlib
import hashlib
import json
import subprocess
import shlex
import sys
path, config, level, groups, opt, compiler, cflags, cxxflags, cppflags = sys.argv[1:]
known = ['cpu', 'gpu', 'threads', 'io', 'network']
selected = groups.split(',') if groups else []
if config not in ('debug', 'release') or level not in ('0', '1', '2', '3') or set(selected) - set(known):
    sys.exit('CONFIG=debug|release, PROBE_LEVEL=0..3, PROBE_GROUPS=cpu,gpu,threads,io,network')
level = int(level) if config == 'debug' else 0
info = {'config': config, 'probe_level': level, 'probe_groups': selected if level else [],
        'optimization': opt, 'compiler': subprocess.check_output(shlex.split(compiler) + ['--version'], text=True).splitlines()[0],
        'cflags': cflags, 'cxxflags': cxxflags, 'cppflags': cppflags}
serialized = json.dumps(info, sort_keys=True, indent=2) + '\n'
digest = hashlib.sha256(serialized.encode()).hexdigest()
lines = ['/* Generated build configuration. */', f'#define WX_BUILD_OPTIONS_HASH \"{digest}\"', '#pragma once', f'#define WX_PROBE_LEVEL {level}', f'#define WX_DEBUG_BUILD {int(config == "debug")}']
lines += [f'#define WX_PROBE_{group.upper()} {int(level > 0 and group in selected)}' for group in known]
content = '\n'.join(lines) + '\n'
p = pathlib.Path(path)
p.parent.mkdir(parents=True, exist_ok=True)
info_path = p.parent / 'build-info.json'
if not info_path.exists() or info_path.read_text() != serialized:
    info_path.write_text(serialized)
if not p.exists() or p.read_text() != content:
    p.write_text(content)
