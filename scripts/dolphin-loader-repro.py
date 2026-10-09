#!/usr/bin/env python3
"""Compare a libogc-only video/exit fixture under Dolphin JIT and interpreter.

Never contacts the Wii. A guest exception remains a failed result, even if the
emulator also shuts down. Artifacts and owned profiles are retained in build/.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
from diagnose import digest, scan_log

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--seconds', type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20 or not 5 <= args.seconds <= 60:
        parser.error('Repeat must be 1..20; seconds 5..60')
    output = Path(tempfile.mkdtemp(prefix='loader-repro-', dir=ROOT/'build'))
    devkit = Path(os.environ.get('DEVKITPRO', '/opt/devkitpro'))
    ppc = Path(os.environ.get('DEVKITPPC', str(devkit/'devkitPPC')))
    source = output/'dolphin_loader_exit.c'
    shutil.copyfile(ROOT/'tests/fixtures/dolphin_loader_exit.c', source)
    elf, dol = output/'boot.elf', output/'boot.dol'
    subprocess.run([str(ppc/'bin/powerpc-eabi-gcc'), '-DGEKKO', '-mrvl', '-mcpu=750',
        '-meabi', '-mhard-float', '-g', '-I'+str(devkit/'libogc/include'), str(source),
        '-L'+str(devkit/'libogc/lib/wii'), '-logc', '-lm', '-o', str(elf)], check=True)
    subprocess.run([str(devkit/'tools/bin/elf2dol'), str(elf), str(dol)], check=True)
    results = []
    for core in ('jit', 'interpreter'):
        for iteration in range(args.repeat):
            prepared = subprocess.check_output(['bash', 'scripts/dolphin.sh', '--build',
                'debug', '--prepare-only', '--cpu-core', core], cwd=ROOT, text=True)
            profile = Path(prepared.strip().split('Dolphin profile, frozen build, and logs: ', 1)[1])
            if profile.resolve().parent != (ROOT/'build').resolve() or not profile.name.startswith('dolphin.'):
                raise ValueError('Prepare returned an unowned profile')
            artifacts = profile/'artifacts'
            # Replace the application's manifest with the actual standalone fixture.
            # This is a new, owned profile; no personal emulator files are touched.
            artifacts.mkdir(exist_ok=True)
            for file in artifacts.iterdir():
                file.unlink()
            for file in (source, elf, dol):
                shutil.copyfile(file, artifacts/file.name)
            (artifacts/'SHA256SUMS').write_text(''.join(
                digest(file)+'  '+file.name+'\n' for file in sorted(artifacts.iterdir())))
            command = json.loads((profile/'launch-command.json').read_text())
            command[command.index('-e')+1] = str(artifacts/'boot.dol')
            record = {'core': core, 'iteration': iteration+1, 'profile': str(profile),
                      'dol_sha256': digest(dol), 'source_sha256': digest(source)}
            try:
                subprocess.run([sys.executable, 'scripts/dolphin-process.py', '--seconds',
                    str(args.seconds), str(profile), *command], cwd=ROOT, check=True,
                    timeout=args.seconds+40)
                report = scan_log(profile/'Logs/dolphin.log', 16*1024*1024)
                record['log'] = report
                # This fixture intentionally has no WiiXplorer cleanup marker.
                record['passed'] = (report['verdict'] == 'missing_app_cleanup'
                                    and report['core_shutdown'])
            except (subprocess.SubprocessError, OSError) as error:
                record.update(passed=False, error=type(error).__name__)
            finally:
                try:
                    subprocess.run([sys.executable, 'scripts/dolphin-process.py',
                        '--stop', str(profile)], cwd=ROOT, check=True, timeout=20)
                except (subprocess.SubprocessError, OSError):
                    record.update(passed=False, cleanup_failed=True)
                    try:
                        subprocess.run([sys.executable, 'scripts/dolphin-process.py',
                            '--force-stop', str(profile)], cwd=ROOT, check=True, timeout=20)
                    except (subprocess.SubprocessError, OSError) as error:
                        record['force_cleanup_error'] = type(error).__name__
                results.append(record)
                (output/'result.json').write_text(json.dumps(results, indent=2)+'\n')
            print(core, iteration+1, 'PASS' if record['passed'] else 'FAIL', flush=True)
    print(output/'result.json')
    return 0 if all(result['passed'] for result in results) else 1


if __name__ == '__main__':
    sys.exit(main())
