#!/usr/bin/env python3
"""Bounded, read-only diagnostic evidence; never contacts or controls a Wii."""
import argparse
from collections import deque
import csv
import hashlib
import json
from pathlib import Path
import re

FAULT = re.compile(r'\b(?:DSI|ISI|machine check|program|alignment|FPU unavailable) exception\b|exception \((?:DSI|ISI)\)|unknown instruction|GFX FIFO: Unknown Opcode|unable to resolve (?:read|write) address|invalid (?:read|write) (?:from|to)|panic alert|stack dump|backtrace:', re.I)
MARKERS = {'app_cleanup': 'WiiXplorer: shutdown cleanup completed',
           'core_shutdown': 'Shutdown complete ----'}

def redact(line):
    # Drop the remainder: spaces/quoted strings are legal password characters.
    return re.sub(r'(?i)(\bPASS\s+|\b(?:password|CPassword|authorization|token)\s*[:=]\s*).*',
                  r'\1<REDACTED>', line)[:2048]

def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()

def read_json(path):
    with Path(path).open('rb') as stream:
        data = stream.read(256 * 1024 + 1)
    if len(data) > 256 * 1024: raise ValueError('JSON exceeds evidence budget')
    return json.loads(data)

def scan_log(path, max_bytes=64 * 1024 * 1024):
    """Stop at first fault plus bounded context; never approve a partial scan."""
    result = {'verdict': 'missing_log', 'scanned_bytes': 0, 'first_fault': None,
              'context': [], **{key: False for key in MARKERS}}
    before = deque(maxlen=8)
    remaining_context = None
    try:
        with Path(path).open('rb') as stream:
            result['log_bytes'] = Path(path).stat().st_size
            while True:
                if result['scanned_bytes'] >= max_bytes:
                    result['verdict'] = 'guest_fault' if result['first_fault'] else 'log_budget'
                    return result
                raw = stream.readline(min(16385, max_bytes - result['scanned_bytes']))
                if not raw: break
                result['scanned_bytes'] += len(raw)
                line = raw.decode(errors='replace').rstrip('\r\n')
                for key, marker in MARKERS.items():
                    if marker in line: result[key] = True
                if result['first_fault'] is None and FAULT.search(line):
                    result['first_fault'] = redact(line)
                    result['context'] = list(before) + [redact(line)]
                    remaining_context = 16
                elif remaining_context is not None:
                    result['context'].append(redact(line))
                    remaining_context -= 1
                    if not remaining_context: break
                else: before.append(redact(line))
                if len(raw) == 16385 and not raw.endswith(b'\n'):
                    result['verdict'] = 'guest_fault' if result['first_fault'] else 'oversized_log_line'
                    return result
    except OSError as error:
        result['error'] = redact(str(error))
        return result
    result['verdict'] = ('guest_fault' if result['first_fault'] else
                         'missing_app_cleanup' if not result['app_cleanup'] else
                         'missing_core_shutdown' if not result['core_shutdown'] else 'clean_shutdown')
    return result

def collect(profile, max_bytes=64 * 1024 * 1024):
    profile = Path(profile)
    result = {'profile': str(profile), 'log': scan_log(profile/'Logs/dolphin.log', max_bytes),
              'artifacts': {}, 'artifact_errors': []}
    try:
        manifest = profile/'artifacts/SHA256SUMS'
        if manifest.stat().st_size > 65536: raise ValueError('Artifact manifest exceeds evidence budget')
        for line in manifest.read_text().splitlines():
            expected, name = line.split('  ', 1)
            if not re.fullmatch(r'[0-9a-f]{64}', expected) or name in ('', '.', '..') or any(c in name for c in '/\\:') or any(ord(c)<32 for c in name):
                raise ValueError('Invalid artifact manifest entry')
            path = profile/'artifacts'/name
            if path.is_symlink(): raise ValueError('Symlink artifact rejected')
            actual = digest(path)
            result['artifacts'][name] = actual
            if actual != expected: result['artifact_errors'].append('Hash mismatch: '+name)
        if not result['artifacts']: raise ValueError('Empty artifact manifest')
    except (OSError, ValueError) as error: result['artifact_errors'].append(redact(str(error)))
    stage = profile/'scenario-stage.json'
    if stage.exists():
        try:
            value = read_json(stage)
            result['scenario_stage'] = redact(str(value['stage']))
        except (OSError, ValueError, KeyError, TypeError): result['scenario_stage'] = 'unreadable'
    result['case_reports'] = {}
    for name in ('features', 'media', 'archive'):
        filename = name+'-results.csv'
        path = profile/filename
        if not path.exists():
            folder = ('wiixplorer-archive-' if name=='archive' else 'wiixplorer-copy-')+profile.name
            path = profile/'Load/WiiSDSync'/folder/filename
        if not path.exists(): continue
        try:
            if path.stat().st_size>65536: raise ValueError('Case report exceeds evidence budget')
            with path.open(newline='') as stream: rows = list(csv.DictReader(stream))
            if not rows or any(None in row or any(value is None for value in row.values()) or row.get('verified') not in ('0','1') for row in rows):
                raise ValueError('Incomplete case report')
            result['case_reports'][name] = {'rows': len(rows),
                'failed': [redact(row.get('case','unknown')) for row in rows if row['verified']=='0']}
        except (OSError, ValueError, csv.Error) as error: result['case_reports'][name] = {'error': redact(str(error))}
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('inspect', 'inventory'))
    parser.add_argument('path', type=Path, help='Dolphin profile, or build directory for inventory')
    parser.add_argument('--max-log-mib', type=int, default=64)
    parser.add_argument('--limit', type=int, default=100, help='most recent validation records, 1..1000')
    parser.add_argument('--output', type=Path, help='optional JSON report; stdout stays compact')
    args = parser.parse_args()
    if not 1 <= args.max_log_mib <= 1024 or not 1 <= args.limit <= 1000:
        parser.error('Evidence budget or record limit out of bounds')
    budget = args.max_log_mib * 1024 * 1024
    if args.mode == 'inspect':
        report = collect(args.path, budget)
        print('artifact_failure' if report['artifact_errors'] else report['log']['verdict'],
              report['log']['first_fault'] or (report['artifact_errors'] or [''])[0], flush=True)
    else:
        report = []
        for path in sorted(args.path.glob('validation-*/result.json'), reverse=True)[:args.limit]:
            try:
                record = read_json(path)
                if not isinstance(record, dict): raise ValueError('Validation record must be an object')
                row = {key: record.get(key) for key in ('bench', 'passed', 'failure_stage', 'queue_job')}
                row['run'] = str(path.parent)
                # Profiles must belong to the supplied build directory.
                profile = Path(record.get('profile') or '')
                if profile.name.startswith('dolphin.') and profile.resolve().parent == args.path.resolve():
                    row['evidence'] = collect(profile, budget)
                report.append(row)
                evidence = row.get('evidence', {})
                print(row['bench'], 'PASS' if row['passed'] else 'FAIL',
                      row['failure_stage'] or 'legacy: stage not recorded',
                      evidence.get('scenario_stage',''), evidence.get('log',{}).get('verdict',''), row['run'])
            except (OSError, ValueError, TypeError) as error:
                report.append({'run': str(path.parent), 'error': redact(str(error))})
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2)+'\n')
    if args.mode == 'inspect' and (report['artifact_errors'] or report['log']['verdict'] != 'clean_shutdown'):
        raise SystemExit(1)

if __name__ == '__main__': main()
