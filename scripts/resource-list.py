#!/usr/bin/env python3
"""Generate resource declarations from asset names; preserve unchanged timestamps."""
from pathlib import Path
import re
import sys
root = Path(__file__).resolve().parent.parent
files = sorted((p for kind in ('images','sounds','fonts') for p in (root/'data'/kind).iterdir()
                if p.is_file() and not p.name.startswith('.')), key=lambda p:p.name.casefold())
lines = ['/* Generated resource table. Do not edit. */', '#pragma once', '#include <gctypes.h>',
         'typedef struct _RecourceFile {', '    const char *filename;', '    const u8 *DefaultFile;',
         '    const u32 DefaultFileSize;', '    u8 *CustomFile;', '    u32 CustomFileSize;', '} RecourceFile;']
seen = set()
for file in files:
    symbol = file.name.replace('.', '_')
    if not re.fullmatch('[A-Za-z_][A-Za-z_0-9]*', symbol) or symbol.casefold() in seen:
        sys.exit('Asset names must create unique C identifiers: '+file.name)
    seen.add(symbol.casefold())
    lines += [f'extern const u8 {symbol}[];', f'extern const u32 {symbol}_size;']
lines.append('static RecourceFile RecourceList[] = {')
for file in files:
    symbol = file.name.replace('.', '_')
    lines.append(f'    {{"{file.name}", {symbol}, {symbol}_size, NULL, 0}},')
lines += ['    {NULL, NULL, 0, NULL, 0}', '};', '']
content = '\n'.join(lines)
output = Path(sys.argv[1])
output.parent.mkdir(parents=True, exist_ok=True)
if not output.exists() or output.read_text() != content:
    temporary = output.with_suffix('.tmp')
    temporary.write_text(content)
    temporary.replace(output)
