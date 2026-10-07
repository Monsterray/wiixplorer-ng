#!/usr/bin/env python3
"""Freeze a debug build, require Dolphin success, then optionally queue that DOL."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bench', choices=('media', 'copy', 'memory', 'archive'))
    parser.add_argument('--hardware', action='store_true')
    parser.add_argument('--capture-device', help='HDMI capture device ID for the queued Wii job')
    parser.add_argument('--wait-port', type=int, default=300, help='wait 0..3600 seconds for another emulator')
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--queue-client', type=Path, default=Path(os.environ.get(
        'WII_BENCH_CLIENT', str(Path.home()/'.wii-bench/wiibench.py'))))
    args = parser.parse_args()
    if not 0<=args.wait_port<=3600: parser.error('--wait-port must be 0..3600')
    if args.capture_device and not args.hardware: parser.error('--capture-device requires --hardware')
    run = ROOT/'build'/time.strftime('validation-%Y%m%d-%H%M%S')
    run.mkdir(parents=True, exist_ok=False)
    summary = {'bench': args.bench, 'passed': False}

    def step(name, command, timeout=600):
        print(name, flush=True)
        with (run/(name+'.log')).open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=timeout)
        return (run/(name+'.log')).read_text()

    profile = None
    try:
        if not args.skip_build:
            step('build', ['make', '-j4', 'debug', 'PROBE_LEVEL=3'])
        output = step('prepare', ['bash', 'scripts/dolphin.sh', '--build', 'debug',
                                 '--bench', args.bench, '--capture', '--prepare-only'])
        prefix = 'Dolphin profile, frozen build, and logs: '
        profile = Path(next(line[len(prefix):] for line in output.splitlines()
                            if line.startswith(prefix)))
        summary['profile'] = str(profile)
        step('port', [sys.executable,'scripts/hbc-port.py','--wait',str(args.wait_port)],timeout=args.wait_port+30)
        command=json.loads((profile/'launch-command.json').read_text())
        step('launch', [sys.executable,'scripts/dolphin-process.py',str(profile),*command],timeout=30)
        option = '--archive-device' if args.bench == 'archive' else '--'+args.bench+'-bench'
        options = [option, 'sd'] if args.bench == 'archive' else [option]
        step('dolphin-smoke', [sys.executable, 'scripts/hbc-smoke.py', '--profile',
                              str(profile), *options])
        step('dolphin-check', [sys.executable, 'scripts/check-dolphin-smoke.py', str(profile)])
        if args.hardware:
            capture = []
            if args.capture_device:
                if sys.platform != 'darwin': parser.error('Native capture helper requires macOS')
                step('capture-build', [sys.executable,'scripts/build-wii-capture.py'])
                capture = ['--capture-device', args.capture_device]
            result = step('queue', [sys.executable, str(args.queue_client), 'add',
                '--name', 'wiixplorer-'+args.bench, '--agent', 'wiixplorer-ng',
                '--timeout', '600', '--cwd', str(ROOT), '--', sys.executable,
                'scripts/hbc-smoke.py', '--hardware', *options, *capture,
                '--build-dir', str(profile/'artifacts')])
            summary['queue_job'] = result.strip()
            step('hardware', [sys.executable, str(args.queue_client), 'wait', result.strip(), '--tail', '200'], timeout=7200)
        summary['passed'] = True
    finally:
        if profile is not None:
            # Existing owner refuses to touch unrelated Dolphin profiles.
            try:
                step('stop', [sys.executable, 'scripts/dolphin-process.py', '--stop', str(profile)])
            except (subprocess.SubprocessError, OSError) as error:
                summary['cleanup_error'] = str(error)
                summary['passed'] = False
        (run/'result.json').write_text(json.dumps(summary, indent=2)+'\n')
        print(run/'result.json', flush=True)

if __name__ == '__main__':
    main()
