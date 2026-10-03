#!/usr/bin/env python3
"""Track only this project's Dolphin profile; never stop an unrelated emulator."""
import argparse
import datetime
import platform
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

root = Path(__file__).resolve().parent.parent
state = root / 'build/dolphin-process.json'
windows = os.name == 'nt' or sys.platform in ('cygwin', 'msys')
prefix = str(root/'build/dolphin.')
if windows and os.name != 'nt':
    prefix = subprocess.check_output(['cygpath', '-w', prefix], text=True).strip()

def processes(profile):
    if windows:
        result = subprocess.run(['powershell', '-NoProfile', '-Command',
            'Get-CimInstance Win32_Process | Where-Object {$_.Name -like "Dolphin*"} | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress'], capture_output=True, text=True, check=True)
        entries = json.loads(result.stdout or '[]')
        if isinstance(entries, dict): entries = [entries]
        return [int(p['ProcessId']) for p in entries
                if (' -u '+profile).casefold() in (p['CommandLine'] or '').replace('\"', '').casefold()]
    executables = subprocess.run(['ps', '-axo', 'pid=,comm='], capture_output=True, text=True, check=True)
    dolphin_pids = {int(parts[0]) for line in executables.stdout.splitlines()
                    if len(parts := line.strip().split(None, 1)) == 2
                    and Path(parts[1]).name in ('Dolphin', 'dolphin-emu', 'dolphin-emu-qt')}
    result = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True, check=True)
    return [int(parts[0]) for line in result.stdout.splitlines()
            if len(parts := line.strip().split(None, 1)) == 2
            and int(parts[0]) in dolphin_pids and (' -u '+profile) in parts[1].replace('\"', '')]

def stop(profile, force=False, timed=False):
    pids = processes(profile)
    for pid in pids:
        if windows:
            command = ['taskkill', '/PID', str(pid)] + (['/F'] if force else [])
            subprocess.run(command, check=False)
        else:
            try: os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
            except ProcessLookupError: pass
    deadline = time.monotonic() + 10
    while processes(profile) and time.monotonic() < deadline: time.sleep(.25)
    if processes(profile):
        if timed:
            print('Timed run required forced shutdown; SD sync may be incomplete.', file=sys.stderr)
            marker = Path(profile)/'forced-stop.txt'
            if marker.parent.is_dir(): marker.write_text('SIGTERM did not close Dolphin within 10 seconds. SD sync may be incomplete.\n')
            stop(profile, force=True)
        else:
            sys.exit('Dolphin did not stop; use --force-stop for this tracked instance. SD sync may be incomplete.')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--force-stop', action='store_true')
    parser.add_argument('--stop-all', action='store_true')
    parser.add_argument('--seconds', type=float, default=0)
    parser.add_argument('profile', nargs='?')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    previous = json.loads(state.read_text()) if state.exists() else None
    if args.stop_all:
        stop(prefix, timed=True)
        sys.exit(0)
    if args.status or args.stop or args.force_stop:
        if previous:
            if args.status: print(json.dumps({'profile':previous['profile'], 'pids':processes(previous['profile'])}))
            else: stop(previous['profile'], args.force_stop)
        else: print('No tracked Dolphin instance.')
        sys.exit(0)
    if processes(prefix): sys.exit('A project Dolphin run is still open. Use scripts/dolphin.sh --stop first.')
    if not args.profile or not args.command: parser.error('profile and launch command required')
    if not 0 <= args.seconds <= 86400: parser.error('--seconds must be between 0 and 86400')
    profile = args.profile if windows else str(Path(args.profile).resolve())
    state.parent.mkdir(exist_ok=True)
    state.write_text(json.dumps({'profile':profile, 'command':args.command}) + '\n')
    local_profile = Path(profile)
    if windows and os.name != 'nt':
        local_profile = Path(subprocess.check_output(['cygpath','-u',profile], text=True).strip())
    metadata = {'command':args.command, 'host':platform.platform(),
                'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (local_profile/'run.json').write_text(json.dumps(metadata, indent=2)+'\n')
    subprocess.Popen(args.command)
    try:
        deadline = time.monotonic() + 10
        while not processes(profile) and time.monotonic() < deadline: time.sleep(.25)
        if not processes(profile): sys.exit('Dolphin did not start.')
        metadata['pids'] = processes(profile)
        (local_profile/'run.json').write_text(json.dumps(metadata, indent=2)+'\n')
        if not args.seconds: sys.exit(0)
        time.sleep(args.seconds)
    except KeyboardInterrupt:
        stop(profile, timed=True)
        sys.exit(130)
    finally:
        if args.seconds: stop(profile, timed=True)

if __name__ == "__main__":
    main()
