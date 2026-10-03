#!/usr/bin/env python3
"""Build the pinned HBC-Reborn SDK locally, including our shutdown patch."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
REVISION = '3b1e9a4e04fbb1afb98f516a2446ef9789877f8f'
SHA256 = '0a62fb10826ea820f820f76925cba79ef78df06f319fb751a9802b0cdba7198b'
SDK = Path(os.environ.get('DEVKITPRO', '/opt/devkitpro'))
PPC = Path(os.environ.get('DEVKITPPC', SDK / 'devkitPPC'))

def main():
    archive = ROOT / '.deps/downloads/hbc-reborn.tar.gz'
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        subprocess.run(['curl', '--fail', '--location', '--retry', '2',
                        f'https://codeload.github.com/Monsterray/hbc-reborn/tar.gz/{REVISION}',
                        '--output', str(archive)], check=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit('HBC-Reborn archive checksum mismatch; remove it and retry.')
    patch = ROOT / 'scripts/patches/hbc-agent.patch'
    fingerprint = hashlib.sha256(Path(__file__).read_bytes() + patch.read_bytes() +
        (ROOT/'source/FileOperations/TransferFile.h').read_bytes() +
        (ROOT/'source/network/TransferSocket.h').read_bytes() +
        subprocess.check_output([str(PPC/'bin/powerpc-eabi-gcc'), '--version'])).hexdigest()
    work = ROOT / '.deps/work/hbc-agent'
    marker = work / '.recipe'
    if not marker.exists() or marker.read_text() != fingerprint:
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                path = Path(member.name)
                if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                    raise SystemExit('Unsafe HBC archive member: '+member.name)
            tar.extractall(work)
        source = work / ('hbc-reborn-' + REVISION)
        subprocess.run(['patch', '-p1', '-i', str(patch)], cwd=source, check=True)
        marker.write_text(fingerprint)
    source = work / ('hbc-reborn-' + REVISION)
    for header in ('FileOperations/TransferFile.h', 'network/TransferSocket.h'):
        shutil.copy2(ROOT/'source'/header, source/'channel/channelapp/source'/Path(header).name)
    env = dict(os.environ, DEVKITPRO=str(SDK), DEVKITPPC=str(PPC))
    subprocess.run(['make', '-C', str(source/'sdk/hbc_agent'), 'OGC=libogc',
                    'EXTRA_CFLAGS=-g'], env=env, check=True)
    prefix = ROOT / '.deps/prefix'
    for destination in ('include', 'lib', 'bin', 'licenses/hbc-agent'):
        (prefix/destination).mkdir(parents=True, exist_ok=True)
    for header in ('hbc_agent.h', 'hbc_netlog.h'):
        shutil.copy2(source/'sdk'/header, prefix/'include'/header)
    shutil.copy2(source/'sdk/hbc_agent/libhbcagent.a', prefix/'lib/libhbcagent.a')
    shutil.copy2(source/'COPYING', prefix/'licenses/hbc-agent/COPYING')
    shutil.copy2(source/'tools/hbc.py', prefix/'bin/hbc.py')

if __name__ == '__main__':
    main()
