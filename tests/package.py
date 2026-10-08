#!/usr/bin/env python3
"""Exercise production packaging, version/config gates and failure preservation."""
from pathlib import Path
import json
import runpy
import tempfile
from unittest.mock import patch
package=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/package.py'))['package']
with tempfile.TemporaryDirectory(prefix='wx-package-') as temporary:
    root=Path(temporary)
    files={'VERSION':'0.1.13\n','HBC/meta.xml':'<app><name>WiiXplorer NG</name><version>0.1.13</version></app>',
           'HBC/icon.png':'icon','Languages/english.lang':'English','LICENSE.md':'notices',
           '.deps/prefix/hbc-agent.json':'{}','DEPENDENCIES.md':'pins','RELEASE-CANDIDATE.md':'test plan',
           'source/FTPOperations/ftpsrv/LICENSE':'MIT','.deps/prefix/licenses/hbc-agent/COPYING':'GPL'}
    for name,text in files.items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    for config in ('release','debug'):
        folder=root/'build'/config;folder.mkdir(parents=True)
        (folder/'boot.dol').write_bytes(b'fixture-'+config.encode())
        (folder/'build-info.json').write_text(json.dumps({'config':config,'probe_level':int(config=='debug'),'probe_groups':['io'] if config=='debug' else []}))
    with patch.dict(package.__globals__,ROOT=root):
        release=package('release');original=(release/'boot.dol').read_bytes()
        assert (release/'Languages/english.lang').exists() and (release/'SHA256SUMS').exists()
        assert not (release/'update.xml').exists() and not (release/'WiiXplorer.cfg').exists()
        debug=package('debug');assert debug!=release and '(debug)' in (debug/'meta.xml').read_text()
        package('release');assert (release/'boot.dol').read_bytes()==original
        (root/'build/release/boot.dol').write_bytes(b'')
        try: package('release')
        except ValueError: pass
        else: raise AssertionError('Empty DOL accepted')
        assert (release/'boot.dol').read_bytes()==original
        (root/'build/release/boot.dol').write_bytes(b'new')
        rename=Path.rename
        def fail_publish(source,target):
            if source.parent.name.startswith('package-'): raise OSError('injected publish failure')
            return rename(source,target)
        with patch.object(Path,'rename',fail_publish):
            try: package('release')
            except OSError: pass
            else: raise AssertionError('Publish failure accepted')
        assert (release/'boot.dol').read_bytes()==original
        (release/'.wiixplorer-package.json').unlink()
        try: package('release')
        except ValueError: pass
        else: raise AssertionError('Unmanaged package replaced')
print('Package: matching versions, separate configs, companion files, failure rollback and unmanaged refusal passed')
