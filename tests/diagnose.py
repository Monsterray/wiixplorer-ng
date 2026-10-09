#!/usr/bin/env python3
"""First fault survives log storms; partial scans/hashes never approve a run."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
module = runpy.run_path(str(ROOT/'scripts/diagnose.py'))
scan, collect = module['scan_log'], module['collect']
with tempfile.TemporaryDirectory(prefix='wx-evidence-') as directory:
    root = Path(directory); profile = root/'dolphin.fixture'
    (profile/'Logs').mkdir(parents=True); (profile/'artifacts').mkdir()
    log = profile/'Logs/dolphin.log'
    okay = b'WiiXplorer: shutdown cleanup completed\nShutdown complete ----\n'
    assert scan(log)['verdict']=='missing_log'
    log.write_bytes(okay); assert scan(log)['verdict']=='clean_shutdown'
    log.write_bytes(okay.splitlines()[0]+b'\n');assert scan(log)['verdict']=='missing_core_shutdown'
    log.write_bytes(okay+b'ordinary record\n'*100000)
    assert scan(log, 1024)['verdict']=='log_budget'
    log.write_bytes(b'x'*20000);assert scan(log)['verdict']=='oversized_log_line'
    with log.open('wb') as stream:
        stream.write(b'PASS private with spaces\nAuthorization: private-token\n'+okay+
                     b'IntCPU: Unknown instruction 00000000 at PC = 80666ca8\nLR = 807b4c40\n')
        stream.seek(512*1024*1024);stream.write(b'\n')
    result = scan(log)
    assert result['verdict']=='guest_fault' and result['scanned_bytes']<32768
    assert '80666ca8' in result['first_fault'] and '807b4c40' in '\n'.join(result['context'])
    assert 'private' not in json.dumps(result) and '<REDACTED>' in json.dumps(result)
    assert module['redact']('CPassword = encoded')=='CPassword = <REDACTED>'
    log.write_bytes(okay)
    artifact = profile/'artifacts/boot.dol';artifact.write_bytes(b'exact binary')
    manifest = profile/'artifacts/SHA256SUMS'
    manifest.write_text(hashlib.sha256(artifact.read_bytes()).hexdigest()+'  boot.dol\n')
    assert not collect(profile)['artifact_errors']
    artifact.write_bytes(b'changed binary');assert collect(profile)['artifact_errors']
    (profile/'features-results.csv').write_text('case,verified\npng,1\ntiff,0\n')
    assert collect(profile)['case_reports']['features']=={'rows':2,'failed':['tiff']}
    (profile/'features-results.csv').write_text('case,verified\npng,\n')
    assert 'error' in collect(profile)['case_reports']['features']
    for name in ('../outside','C:outside','', '..'):
        manifest.write_text('0'*64+'  '+name+'\n')
        assert collect(profile)['artifact_errors']
    record = root/'validation-fixture';record.mkdir()
    (record/'result.json').write_text(json.dumps({'bench':'exit','passed':False,'failure_stage':'dolphin-smoke','profile':str(profile)}))
    output = root/'inventory.json'
    command = ['python3',str(ROOT/'scripts/diagnose.py'),'inventory',str(root),'--output',str(output)]
    completed = subprocess.run(command,capture_output=True,text=True,check=True)
    assert 'FAIL dolphin-smoke' in completed.stdout
    rows=json.loads(output.read_text());assert rows[0]['evidence']['artifact_errors']
    (record/'result.json').write_text('[]')
    subprocess.run(command,capture_output=True,check=True)
    assert 'error' in json.loads(output.read_text())[0]
print('Diagnostics: first fault/context, secret redaction, bounded log storms, incomplete scans, artifact tamper/path guards and legacy inventory passed')
