#!/usr/bin/env python3
"""Stage a ready-to-copy Homebrew app without touching user settings or templates."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]

def package(config):
    version=(ROOT/'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+',version): raise ValueError('Invalid VERSION')
    if ET.parse(ROOT/'HBC/meta.xml').findtext('version')!=version:
        raise ValueError('HBC metadata version differs from VERSION')
    build=ROOT/'build'/config
    info=json.loads((build/'build-info.json').read_text())
    if info['config']!=config: raise ValueError('Build configuration mismatch')
    if config=='release' and (info['probe_level'] or info['probe_groups']):
        raise ValueError('Release includes diagnostic probes')
    folder=ROOT/'release';folder.mkdir(exist_ok=True)
    destination=folder/('wiixplorer' if config=='release' else 'wiixplorer-debug')
    marker='.wiixplorer-package.json'
    if destination.exists() and (destination.is_symlink() or not (destination/marker).is_file()):
        raise ValueError('Refusing to replace an unmanaged package directory: '+str(destination))
    backup=destination.with_name(destination.name+'.previous')
    if backup.exists(): raise ValueError('Previous interrupted package retained: '+str(backup))
    with tempfile.TemporaryDirectory(prefix='package-',dir=folder) as temporary:
        stage=Path(temporary)/destination.name;stage.mkdir()
        for name,source in [('boot.dol',build/'boot.dol'),('meta.xml',ROOT/'HBC/meta.xml'),('icon.png',ROOT/'HBC/icon.png')]:
            if not source.is_file() or source.stat().st_size==0: raise ValueError('Missing/empty package input: '+str(source))
            shutil.copy2(source,stage/name)
        if config=='debug':
            meta=ET.parse(stage/'meta.xml');meta.find('name').text+=' (debug)'
            meta.write(stage/'meta.xml',encoding='utf-8',xml_declaration=True)
        shutil.copytree(ROOT/'Languages',stage/'Languages')
        for name in ('LICENSE.md','DEPENDENCIES.md','RELEASE-CANDIDATE.md'):
            shutil.copy2(ROOT/name,stage/name)
        licenses=stage/'licenses';licenses.mkdir()
        shutil.copy2(ROOT/'source/FTPOperations/ftpsrv/LICENSE',licenses/'ftpsrv-MIT.txt')
        shutil.copy2(ROOT/'.deps/prefix/licenses/hbc-agent/COPYING',licenses/'hbc-agent-GPL.txt')
        for path in sorted((ROOT/'.deps/work').glob('*/*')):
            if path.is_file() and path.name.lower() in ('copying','license','license.txt'):
                shutil.copy2(path,licenses/(path.parent.name+'-'+path.name))
        shutil.copy2(build/'build-info.json',stage/'build-info.json')
        shutil.copy2(ROOT/'.deps/prefix/hbc-agent.json',stage/'hbc-agent.json')
        hashes={str(path.relative_to(stage)).replace('\\','/'):hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(stage.rglob('*')) if path.is_file()}
        (stage/marker).write_text(json.dumps({'version':version,'config':config,'sha256':hashes},indent=2)+'\n')
        (stage/'SHA256SUMS').write_text(''.join(digest+'  '+name+'\n' for name,digest in hashes.items()))
        previous=destination.exists()
        if previous: destination.rename(backup)
        try: stage.rename(destination)
        except OSError:
            if previous: backup.rename(destination)
            raise
        if previous: shutil.rmtree(backup)
    print(destination)
    return destination

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',choices=('debug','release'),default='release')
    package(parser.parse_args().config)
