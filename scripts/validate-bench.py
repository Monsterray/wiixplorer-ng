#!/usr/bin/env python3
"""Freeze a debug build, require Dolphin success, then optionally queue that DOL."""
import argparse
import datetime
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from diagnose import collect, digest, redact, read_json

ROOT = Path(__file__).resolve().parents[1]

def validate(args, expected_hash=None):
    run = Path(tempfile.mkdtemp(prefix=time.strftime('validation-%Y%m%d-%H%M%S-'), dir=ROOT/'build'))
    summary = {'schema': 1, 'bench': args.bench, 'cpu_core': args.cpu_core,
               'passed': False, 'steps': []}
    active_stage = None

    def step(name, command, timeout=600):
        nonlocal active_stage
        active_stage = name
        print(name, flush=True)
        record = {'stage': name, 'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        summary['steps'].append(record)
        started = time.monotonic()
        try:
            with (run/(name+'.log')).open('w') as log:
                result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                        check=True, timeout=timeout)
            record['returncode'] = result.returncode if result is not None else 0
        except (subprocess.SubprocessError, OSError) as error:
            record.update(error=type(error).__name__, returncode=getattr(error, 'returncode', None))
            raise
        finally: record['seconds'] = round(time.monotonic()-started, 3)
        # Only prepare/queue output is consumed. Never load a compiler/fault log into RAM.
        with (run/(name+'.log')).open() as log: return log.read(65536)

    profile = None
    try:
        if not args.skip_build:
            step('build', ['make', '-j4', 'debug', 'PROBE_LEVEL=3'])
        prepare = ['bash', 'scripts/dolphin.sh', '--build', 'debug', '--prepare-only',
                   '--cpu-core', args.cpu_core]
        if args.bench != 'exit': prepare.append('--capture')
        if args.bench == 'ftp':
            password = secrets.token_hex(12)
            encoded = bytes(ord(c)^ord('WiiXplorer'[i%10]) for i,c in enumerate(password)).hex()
            config = run/'ftp.cfg'
            with config.open('x') as stream:
                os.chmod(config, 0o600)
                stream.write('BootIOS = 58\nAutoConnect = 0\nDeleteTempPath = 0\n'
                    'FTPServer.AutoStart = 1\nFTPServer.Anonymous = 0\nFTPServer.User = wiixplorer\n'
                    'FTPServer.IdleTimeout = 10\nFTPServer.Port = 2121\nFTPServer.CPassword = '+encoded+'\n')
            prepare += ['--config-seed', str(config)]
        elif args.bench != 'exit': prepare += ['--bench', args.bench]
        output = step('prepare', prepare)
        prefix = 'Dolphin profile, frozen build, and logs: '
        profile = Path(next(line[len(prefix):] for line in output.splitlines() if line.startswith(prefix)))
        if profile.resolve().parent != (ROOT/'build').resolve() or not profile.name.startswith('dolphin.'):
            raise ValueError('Prepare returned a profile outside this project')
        summary['profile'] = str(profile)
        active_stage = 'artifact'
        summary['dol_sha256'] = digest(profile/'artifacts/boot.dol')
        if expected_hash and summary['dol_sha256'] != expected_hash:
            raise ValueError('DOL changed during repeat series; no emulator/hardware submitted')
        step('port', [sys.executable,'scripts/hbc-port.py','--wait',str(args.wait_port)], timeout=args.wait_port+30)
        command = json.loads((profile/'launch-command.json').read_text())
        step('launch', [sys.executable,'scripts/dolphin-process.py',str(profile),*command], timeout=30)
        options = (['--exit-only'] if args.bench == 'exit' else ['--ftp-smoke'] if args.bench == 'ftp' else
                   ['--archive-device', 'sd'] if args.bench == 'archive' else ['--'+args.bench+'-bench'])
        options += ['--max-log-mib', str(args.max_log_mib)]
        step('dolphin-smoke', [sys.executable, 'scripts/hbc-smoke.py', '--profile', str(profile), *options],
             timeout=args.smoke_timeout)
        step('stop', [sys.executable, 'scripts/dolphin-process.py', '--stop', str(profile)])
        step('dolphin-check', [sys.executable, 'scripts/check-dolphin-smoke.py', str(profile),
                               '--max-log-mib', str(args.max_log_mib)])
        if args.hardware:
            capture = []
            if args.capture_device:
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
    except (subprocess.SubprocessError, OSError, ValueError, StopIteration, KeyboardInterrupt) as error:
        summary.update(failure_stage=active_stage, error=type(error).__name__)
        if isinstance(error, (ValueError, OSError)): summary['detail'] = redact(str(error))
    finally:
        if profile is not None:
            try:
                step('cleanup-stop', [sys.executable, 'scripts/dolphin-process.py', '--stop', str(profile)])
            except (subprocess.SubprocessError, OSError) as error:
                summary.update(cleanup_error=type(error).__name__, passed=False)
                summary.setdefault('failure_stage', 'cleanup-stop')
                try:
                    step('cleanup-force-stop', [sys.executable, 'scripts/dolphin-process.py', '--force-stop', str(profile)])
                except (subprocess.SubprocessError, OSError) as forced_error:
                    summary['force_cleanup_error'] = type(forced_error).__name__
            evidence = collect(profile, args.max_log_mib * 1024 * 1024)
            (run/'diagnostics.json').write_text(json.dumps(evidence, indent=2)+'\n')
        hardware_log = run/'hardware.log'
        if hardware_log.exists():
            with hardware_log.open() as stream: lines = stream.read(65536).splitlines()
            for line in lines:
                if not line.startswith('HBC smoke artifacts: '): continue
                hardware = Path(line.split(': ', 1)[1])
                if hardware.resolve().parent != (ROOT/'build').resolve() or not hardware.name.startswith('wii.'): continue
                summary['hardware_profile'] = str(hardware)
                try: summary['hardware_stage'] = redact(str(read_json(hardware/'scenario-stage.json')['stage']))
                except (OSError, ValueError, KeyError, TypeError): pass
        (run/'result.json').write_text(json.dumps(summary, indent=2)+'\n')
        print(('PASS' if summary['passed'] else 'FAIL')+' '+args.bench+' '+str(summary.get('failure_stage', '')),
              flush=True)
        print(run/'result.json', flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bench', choices=('exit', 'media', 'copy', 'memory', 'archive', 'features', 'ftp'))
    parser.add_argument('--hardware', action='store_true')
    parser.add_argument('--capture-device', help='HDMI capture device ID for the queued Wii job')
    parser.add_argument('--wait-port', type=int, default=300)
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--cpu-core', choices=('jit', 'interpreter'), default='jit',
                        help='explicit Dolphin mode; guest faults still fail the gate')
    parser.add_argument('--repeat', type=int, default=1, help='1..100 sequential repeats; stop on first failure')
    parser.add_argument('--smoke-timeout', type=int, default=600, help='host smoke watchdog, 30..3600 seconds')
    parser.add_argument('--max-log-mib', type=int, default=64, help='complete scan budget, 1..1024 MiB')
    parser.add_argument('--queue-client', type=Path, default=Path(os.environ.get('WII_BENCH_CLIENT', str(ROOT/'.deps/prefix/bin/wiibench.py'))))
    args = parser.parse_args()
    if args.hardware and args.cpu_core != 'jit':
        parser.error('Hardware requires the normal-JIT gate; interpreter mode is diagnostic only')
    if not 0<=args.wait_port<=3600 or not 1<=args.repeat<=100 or not 30<=args.smoke_timeout<=3600 or not 1<=args.max_log_mib<=1024:
        parser.error('Wait/repeat/timeout/log budget out of bounds')
    if args.capture_device and (not args.hardware or sys.platform != 'darwin'):
        parser.error('HDMI capture requires a queued macOS hardware job')
    (ROOT/'build').mkdir(exist_ok=True)
    expected = None
    for _ in range(args.repeat):
        result = validate(args, expected)
        if not result['passed']: raise SystemExit(130 if result.get('error') == 'KeyboardInterrupt' else 1)
        expected = result['dol_sha256']
        args.skip_build = True

if __name__ == '__main__': main()
