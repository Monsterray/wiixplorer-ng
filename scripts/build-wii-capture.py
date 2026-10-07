#!/usr/bin/env python3
"""Build the optional macOS capture helper only when its inputs change."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]

def build():
    if sys.platform!='darwin': raise SystemExit('HDMI helper requires macOS')
    source=ROOT/'scripts/wii-capture.m'
    plist=ROOT/'scripts/wii-capture.plist'
    directory=ROOT/'build/tools'
    directory.mkdir(parents=True,exist_ok=True)
    output=directory/'wii-capture'
    stamp=directory/'wii-capture.sha256'
    digest=hashlib.sha256(source.read_bytes()+plist.read_bytes()+Path(__file__).read_bytes()).hexdigest()
    if output.is_file() and stamp.is_file() and stamp.read_text().strip()==digest:
        print(output);return
    with tempfile.TemporaryDirectory(prefix='capture-build-',dir=directory) as temporary:
        executable=Path(temporary)/'wii-capture'
        subprocess.run(['clang','-fobjc-arc','-framework','Foundation','-framework',
            'AVFoundation','-framework','CoreImage','-framework','CoreMedia','-framework',
            'AppKit','-Wl,-sectcreate,__TEXT,__info_plist,'+str(plist),
            str(source),'-o',str(executable)],check=True)
        subprocess.run(['codesign','--force','--sign','-','--identifier',
                        'org.wiixplorer-ng.dev-capture',str(executable)],check=True)
        executable.replace(output)
    stamp.write_text(digest+'\n')
    print(output)

if __name__=='__main__': build()
