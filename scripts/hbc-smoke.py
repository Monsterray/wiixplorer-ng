#!/usr/bin/env python3
"""Exercise the pinned HBC-Reborn client in Dolphin or a leased physical Wii job."""
import argparse
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import time
import random
import statistics
import struct
import zlib
import ftplib
import io
import secrets
import threading
import subprocess

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument('--profile', type=Path, help='active isolated Dolphin profile')
mode.add_argument('--hardware', action='store_true', help='only inside a wii-bench job')
parser.add_argument('--ftp-port', type=int, help='override the FTP fixture port (default Wii 21, Dolphin 2121)')
parser.add_argument('--ftp-smoke', action='store_true', help='temporary authenticated FTP server roundtrip, append/resume, idle timeout and exit')
parser.add_argument('--capture-device', help='macOS HDMI device ID; leased hardware jobs only, no camera prompts')
parser.add_argument('--capture-log', action='store_true', help='capture debug stdout through HBC-Reborn on port 4300 when no log target is already set')
parser.add_argument('--archive-device', choices=['sd','usb1'], help='native production archive fixtures on an isolated test directory')
parser.add_argument('--media-bench', action='store_true', help='debug-only native media parser/buffer safety validation')
parser.add_argument('--memory-bench', action='store_true', help='debug-only native MEM1/MEM2/locked-cache benchmark')
parser.add_argument('--storage-device', choices=['sd']+['usb'+str(i) for i in range(1,9)], help='debug-only native storage read/write/copy benchmark')
parser.add_argument('--copy-bench', action='store_true', help='debug-only on-device copy buffer comparison')
parser.add_argument('--transfer-bench', action='store_true', help='8 MiB throughput and failed-upload preservation checks')
parser.add_argument('--transfer-mib', type=int, default=8, help='transfer fixture size, 1..64 MiB (default 8)')
parser.add_argument('--transfer-repeats', type=int, default=3, help='throughput repetitions, 1..10 (default 3)')
parser.add_argument('--build-dir', type=Path, default=ROOT/'build/debug', help='frozen debug artifacts for comparisons')
a = parser.parse_args()
if not 1 <= a.transfer_mib <= 64 or not 1 <= a.transfer_repeats <= 10:
    parser.error("Transfer size/repetitions out of bounds")
client = ROOT/'.deps/prefix/bin/hbc.py'
if not client.exists(): parser.error('Build the SDK first: python3 scripts/build-hbc-agent.py')
spec = importlib.util.spec_from_file_location('hbc_client', client)
hbc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hbc)

if a.capture_device and not a.hardware: parser.error('HDMI capture requires a queued hardware job')
if a.storage_device and a.storage_device!='sd' and not a.hardware: parser.error('Dolphin does not validate physical USB mounts')
if a.archive_device=='usb1' and not a.hardware: parser.error('Dolphin does not validate physical USB mounts')
# Dolphin executes memory operations for correctness; its timings are not hardware speeds.
if sum(bool(x) for x in (a.memory_bench,a.storage_device,a.copy_bench,a.archive_device,a.media_bench))>1: parser.error('Choose one benchmark')

if a.hardware:
    if not os.environ.get('WII_BENCH_JOB_START') or not os.environ.get('WII_BENCH_IP'):
        parser.error('Hardware tests require the shared wii-bench queue/lease')
    address = os.environ['WII_BENCH_IP']
    profile = Path(tempfile.mkdtemp(prefix='wii.', dir=ROOT/'build'))
    artifacts = profile/'artifacts'; artifacts.mkdir()
    for name in ('boot.dol','boot.elf','boot.map','probe-config.h','build-info.json'):
        shutil.copy2(a.build_dir/name, artifacts/name)
    info = json.loads((artifacts/'build-info.json').read_text())
    if info['config'] != 'debug': parser.error('Hardware smoke requires a debug build')
    (artifacts/'SHA256SUMS').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n'
        for p in sorted(artifacts.iterdir()) if p.is_file()))
    before = hbc.status(address)
    if before.get('agent'): raise RuntimeError('Wii already running another app; leave it alone')
    (profile/'hbc-before.json').write_text(json.dumps(before,indent=2))
else:
    profile = a.profile.resolve()
    if profile.parent != ROOT/'build' or not profile.name.startswith('dolphin.'):
        parser.error('Use this project\'s isolated Dolphin profile')
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as udp:
        udp.connect(('192.0.2.1',9)) # Route lookup only; sends no packet.
        address = udp.getsockname()[0]

remote = 'sd:/wiixplorer-test-agent-'+profile.name+'.bin'
uploaded = False
copy_directory = 'sd:/wiixplorer-copy-'+profile.name
storage_directory = (a.storage_device or 'sd')+':/wiixplorer-copy-'+profile.name
ftp_port = a.ftp_port if a.ftp_port is not None else (21 if a.hardware else 2121)
if not 1 <= ftp_port <= 65535: parser.error('FTP port must be 1..65535')
ftp_user = "wiixplorer-test" if a.hardware else "wiixplorer"
ftp_password = secrets.token_hex(12) if a.ftp_smoke else None
if a.ftp_smoke and not a.hardware:
    config = profile/'Load/WiiSDSync/apps/WiiXplorer/WiiXplorer.cfg'
    fields = dict(line.split('=',1) for line in config.read_text().splitlines() if '=' in line)
    fields = {key.strip(): value.strip() for key,value in fields.items()}
    ftp_user = fields.get('FTPServer.User', 'wiixplorer')
    encoded = bytes.fromhex(fields.get('FTPServer.CPassword', ''))
    if not encoded: parser.error('Dolphin FTP smoke requires a password in --config-seed')
    ftp_password = ''.join(chr(c ^ ord('WiiXplorer'[i%10])) for i,c in enumerate(encoded))
ftp_connection = ftp_data = None
ftp_devices = []
copy_owned = False
log_server = None
capture_process = capture_log = None
archive_directory='sd:/wiixplorer-archive-'+profile.name
archive_usb_directory='usb1:/wiixplorer-archive-'+profile.name
# HBC's USB service is avoided; the app copies/validates/cleans its USB fixtures.
archive_transport_directory=archive_directory
archive_owned=False
archive_cleanup=set()
backups = {}
created_dirs = []
try:
    if a.capture_device:
        helper=ROOT/'build/tools/wii-capture'
        if not helper.exists(): raise RuntimeError('Build the HDMI capture helper before queuing the job')
        capture_log=(profile/'capture.log').open('w')
        capture_process=subprocess.Popen([str(helper),a.capture_device,str(profile/'video'),'600'],stdout=capture_log,stderr=subprocess.STDOUT)
        time.sleep(1)
        if capture_process.poll() is not None: raise RuntimeError('HDMI capture did not start; see capture.log (no privacy prompt was opened)')
    if a.hardware:
        # Restore every file the app's settings/probes can replace. No temp cleanup.
        for directory in ('sd:/apps', 'sd:/apps/WiiXplorer'):
            try: hbc.file_request(address,'L',directory+'/')
            except hbc.HBCError as error:
                if error.code != hbc.ENOENT: raise
                hbc.file_request(address,'M',directory)
                if directory != 'sd:/apps': created_dirs.append(directory)
        for name in ('WiiXplorer.cfg','WiiXplorer_Controls.cfg','probes.csv','memory-probes.csv'):
            remote_config='sd:/apps/WiiXplorer/'+name
            try: content=hbc.get_file(address,remote_config)
            except hbc.HBCError as error:
                if error.code != hbc.ENOENT: raise
                content=None
            backups[remote_config]=content
            if content is not None:
                (profile/('original-'+name)).write_bytes(content)
        config=b'BootIOS = 58\nAutoConnect = 0\nDeleteTempPath = 0\n'
        if a.ftp_smoke:
            encoded=bytes(ord(c)^ord('WiiXplorer'[i%10]) for i,c in enumerate(ftp_password)).hex()
            config+=('FTPServer.AutoStart = 1\nFTPServer.User = wiixplorer-test\nFTPServer.IdleTimeout = 30\nFTPServer.Port = '+str(ftp_port)+'\nFTPServer.CPassword = '+encoded+'\n').encode()
        hbc.put_file(address,'sd:/apps/WiiXplorer/WiiXplorer.cfg',config)
        arguments=['--smoke-frames='+('36000' if a.transfer_bench or a.copy_bench or a.storage_device or a.memory_bench or a.media_bench or a.archive_device or a.ftp_smoke else '3600')]
        if a.copy_bench or a.storage_device or a.memory_bench or a.media_bench:
            try: hbc.file_request(address,'L',copy_directory+'/')
            except hbc.HBCError as error:
                if error.code != hbc.ENOENT: raise
            else: raise RuntimeError('Copy benchmark directory already exists')
            copy_owned=True
            if a.media_bench: arguments.append('--media-bench='+copy_directory)
            elif a.memory_bench: arguments.append('--memory-bench='+copy_directory)
            elif a.storage_device:
                arguments+=['--storage-bench='+storage_directory,'--storage-report='+copy_directory]
            else: arguments.append('--copy-bench='+copy_directory)
        if a.archive_device:
            import runpy
            fixture_root=profile/'archive-fixtures'
            manifest=runpy.run_path(str(ROOT/'scripts/archive-fixtures.py'))['generate'](fixture_root)
            hbc.file_request(address,'M',archive_transport_directory) # Never reuse an existing root.
            archive_owned=True
            for path in sorted(fixture_root.iterdir()):
                archive_cleanup.add(path.name)
                hbc.put_file(address,archive_transport_directory+'/'+path.name,path.read_bytes())
            for row in manifest:
                name,success,count,member,bytes_,crc=row.split()
                prefix='out-'+name
                parts=member.split('/')
                archive_cleanup.update(prefix+'/'+ '/'.join(parts[:i]) for i in range(1,len(parts)+1))
                archive_cleanup.add(prefix)
            archive_cleanup.update(('out-good.zip/zero','out-good.zip/empty','out-good.7z/aaa','out-good.7z/zero','out-good.7z/empty','archive-complete','archive-results.csv','created.zip','packtree/sub/payload','packtree/sub','packtree/empty','packtree','out-pack/packed/sub/payload','out-pack/packed/sub','out-pack/packed/empty','out-pack/packed','out-pack'))
            arguments.append('--archive-check='+archive_directory)
            if a.archive_device=='usb1': arguments.append('--archive-output='+archive_usb_directory)
        if a.capture_log:
            if before.get('log'): raise RuntimeError('An existing HBC log target must be preserved; omit --capture-log')
            class SavedLog(hbc.LogServer):
                @staticmethod
                def write(chunk):
                    with (profile/'app.log').open('ab') as stream: stream.write(chunk)
            log_server=SavedLog(4300,address)
            log_server.register(address)
            threading.Thread(target=log_server.serve,args=(True,),daemon=True).start()
        hbc.send(address,str(artifacts/'boot.dol'),arguments)
    print('HBC smoke artifacts:', profile, flush=True)
    deadline = time.monotonic()+(300 if a.memory_bench or a.media_bench else 30)
    while True:
        try:
            status = hbc.status(address)
            if status.get('agent') and status.get('app') == 'WiiXplorer NG': break
        except (OSError,hbc.HBCError):
            pass
        if time.monotonic()>deadline: raise RuntimeError('WiiXplorer agent did not start')
        time.sleep(.5)
    (profile/'hbc-status.json').write_text(json.dumps(status,indent=2))
    if a.hardware: hbc.foreign_app_check(address)

    if a.media_bench:
        deadline=time.monotonic()+180
        while True:
            try:
                complete=hbc.get_file(address,copy_directory+'/media-complete')
                report=hbc.get_file(address,copy_directory+'/media-results.csv')
                (profile/'media-results.csv').write_bytes(report)
                if complete!=b'1': raise RuntimeError('Native media validation failed; see media-results.csv')
                break
            except (OSError,hbc.HBCError): pass
            if time.monotonic()>deadline: raise RuntimeError('Media validation incomplete')
            time.sleep(1)
        rows=list(csv.DictReader(report.decode().splitlines()))
        if len(rows)!=7 or any(r['verified']!='1' for r in rows): raise RuntimeError('Media validation report failed')
        (profile/'media-results.csv').write_bytes(report)
        for name in ('media-results.csv','media-complete'):
            hbc.file_request(address,'D',copy_directory+'/'+name)
        hbc.file_request(address,'D',copy_directory)
        print('Native media: seven production parser/buffer/render groups passed',flush=True)
    def shot(name):
        w,h,pixels = hbc.screen(address)
        if w < 320 or h < 200: raise RuntimeError('Invalid framebuffer dimensions')
        (profile/name).write_bytes(hbc.yuyv_png(w,h,pixels))

    def key(keys):
        # SDK navigation is paced in guest frames. Separate presses so slow
        # emulation/animations cannot consume A before a preceding direction.
        for pressed in keys:
            hbc.send_keys(address,pressed)
            time.sleep(.75)

    if a.archive_device:
        if not a.hardware: manifest=(profile/'Load/WiiSDSync'/archive_directory[4:]/'manifest').read_text().splitlines()
        deadline=time.monotonic()+120
        while True:
            try: complete=hbc.get_file(address,archive_directory+'/archive-complete')
            except hbc.HBCError as error:
                if error.code != hbc.ENOENT: raise
            else: break
            if time.monotonic()>deadline: raise RuntimeError('Native archive checks did not complete')
            # Expected SDK allocation failures display an OK dialog. Only this
            # explicit fixture run acknowledges it; ordinary smoke never does.
            hbc.send_keys(address,'a')
            time.sleep(1)
        report=hbc.get_file(address,archive_directory+'/archive-results.csv')
        (profile/'archive-results.csv').write_bytes(report)
        rows=list(csv.DictReader(report.decode().splitlines()))
        if complete!=b'1' or len(rows)!=len(manifest)+1 or any(r['verified']!='1' for r in rows):
            raise RuntimeError('Native archive integrity/preservation case failed: '+report.decode())
        for directory in (() if a.archive_device=='usb1' else ('out-good.zip/empty','out-good.7z/empty','out-pack/packed/empty')):
            hbc.file_request(address,'L',archive_directory+'/'+directory+'/')
        for filename in (() if a.archive_device=='usb1' else ('out-good.zip/zero','out-good.7z/zero')):
            if hbc.get_file(address,archive_directory+'/'+filename)!=b'': raise RuntimeError('Empty file differs')
        print(f'Native {a.archive_device} archives: {len(rows)} real codec/parser, CRC, traversal and preservation cases passed',flush=True)
    if a.memory_bench:
        deadline=time.monotonic()+300
        while True:
            try:
                complete=hbc.get_file(address,copy_directory+'/memory-complete')
                if complete!=b'1': raise RuntimeError('Memory benchmark allocation, coherence or verification failed')
                report=hbc.get_file(address,copy_directory+'/memory-benchmark.csv')
                break
            except (OSError,hbc.HBCError): pass
            if time.monotonic()>deadline: raise RuntimeError('Memory benchmark incomplete')
            time.sleep(1)
        rows=list(csv.DictReader(report.decode().splitlines()))
        if len(rows)!=144 or any(r['verified']!='1' or int(r['ticks_us'])<=0 or int(r['bytes'])!=8388608 for r in rows):
            raise RuntimeError('Memory benchmark report failed verification')
        aliases=('MEM1-K0','MEM1-K1','MEM2-K0','MEM2-K1')
        expected_groups=[('memcpy',src,dst,262144) for src in ('MEM1','MEM2') for dst in ('MEM1','MEM2')]
        expected_groups += [('crc32_cached',src,'CPU',262144) for src in ('MEM1','MEM2')]
        expected_groups += [('read32_hot',src,'CPU',8192) for src in ('MEM1','MEM2','LC')]
        expected_groups += [('write32_hot','CPU',dst,8192) for dst in ('MEM1','MEM2','LC')]
        expected_groups += [('dma_load',src,'LC',8192) for src in ('MEM1','MEM2')]
        expected_groups += [('dma_store','LC',dst,8192) for dst in ('MEM1','MEM2')]
        expected_groups += [('copy32_alias',src,dst,262144) for src in aliases for dst in aliases]
        for suffix,block in (('hot',8192),('stream',262144)):
            expected_groups += [('read32_alias_'+suffix,src,'CPU',block) for src in aliases]
            expected_groups += [('write32_alias_'+suffix,'CPU',dst,block) for dst in aliases]
        expected={(op,src,dst,block,repeat) for op,src,dst,block in expected_groups for repeat in range(3)}
        actual={(r['operation'],r['source'],r['destination'],int(r['block_bytes']),int(r['repeat'])) for r in rows}
        if actual!=expected: raise RuntimeError('Memory benchmark missing/duplicate alias or operation groups')
        (profile/'memory-benchmark.csv').write_bytes(report)
        capacity=hbc.get_file(address,copy_directory+'/memory-capacity.csv')
        (profile/'memory-capacity.csv').write_bytes(capacity)
        working=hbc.get_file(address,copy_directory+'/memory-workingset.csv')
        (profile/'memory-workingset.csv').write_bytes(working)
        samples=list(csv.DictReader(working.decode().splitlines()))
        sizes=(8192,16384,32768,65536,131072,262144,524288,1048576)
        expected={('copy_crc',src,dst,state,size,0,repeat)
            for src in ('MEM1','MEM2') for dst in aliases
            for state in ('cold','reused') for size in sizes for repeat in range(3)}
        expected|={('read_stride',src,'CPU',state,size,stride,repeat)
            for src in ('MEM1','MEM2') for state in ('cold','reused')
            for size in sizes for stride in (4,32,512,4096) for repeat in range(3)}
        actual={(r['operation'],r['source'],r['destination'],r['cache_state'],
            int(r['block_bytes']),int(r['stride_bytes']),int(r['repeat'])) for r in samples}
        if len(samples)!=768 or actual!=expected or any(r['verified']!='1' or int(r['bytes'])!=2097152 or int(r['ticks_us'])<=0 for r in samples):
            raise RuntimeError('Working-set pipeline/stride report failed verification')
        summary={}
        for row in samples:
            working_key='/'.join(row[field] for field in ('operation','source','destination','cache_state','block_bytes','stride_bytes'))
            summary.setdefault(working_key,[]).append(int(row['ticks_us']))
        (profile/'memory-workingset-summary.json').write_text(json.dumps({key:{'median_us':statistics.median(values),'max_us':max(values)} for key,values in summary.items()},indent=2))
        print('Working-set benchmark: 768 verified copy/CRC and stride rows, 8 KiB–1 MiB; median/max summary saved',flush=True)

        if a.hardware: print(capacity.decode().strip(),flush=True)
        hbc.file_request(address,'D',copy_directory+'/memory-capacity.csv')
        groups={}
        for row in rows:
            group_key=(row['operation'],row['source'],row['destination'])
            groups.setdefault(group_key,[]).append(int(row['bytes'])/1048576/(int(row['ticks_us'])/1000000))
        for (operation,src,dst),speeds in (groups.items() if a.hardware else ()):
            print(f'{operation} {src}->{dst}: median {statistics.median(speeds):.3f} MiB/s ({len(speeds)} verified runs)',flush=True)
        if not a.hardware: print('Dolphin memory correctness: 144 verified operations; emulator timings are not Wii bandwidth',flush=True)
        hbc.file_request(address,'D',copy_directory+'/memory-complete')
        hbc.file_request(address,'D',copy_directory+'/memory-benchmark.csv')
        hbc.file_request(address,'D',copy_directory+'/memory-workingset.csv')
        hbc.file_request(address,'D',copy_directory)

    if a.copy_bench or a.storage_device:
        filename='storage-benchmark.csv' if a.storage_device else 'copy-benchmark.csv'
        expected=12 if a.storage_device else 15
        deadline=time.monotonic()+300
        while True:
            try:
                if a.storage_device and hbc.get_file(address,copy_directory+'/storage-complete')!=b'1':
                    raise RuntimeError('Storage benchmark I/O, verification or cleanup failed')
                report=hbc.get_file(address,copy_directory+'/'+filename)
                rows=list(csv.DictReader(report.decode().splitlines()))
                if len(rows)==expected: break
                if any(row.get('verified')=='0' for row in rows): raise RuntimeError('Storage I/O or checksum failure')
            except (OSError,hbc.HBCError): pass
            if time.monotonic()>deadline: raise RuntimeError('Storage benchmark incomplete')
            time.sleep(2)
        if any(row['verified']!='1' or int(row['bytes'])!=8388608 or int(row['microseconds'])<=0 for row in rows):
            raise RuntimeError('Storage benchmark verification failed')
        (profile/filename).write_bytes(report)
        hbc.file_request(address,'D',copy_directory+'/'+filename)
        if a.storage_device:
            metadata=hbc.get_file(address,copy_directory+'/storage-metadata.csv')
            (profile/'storage-metadata.csv').write_bytes(metadata)
            hbc.file_request(address,'D',copy_directory+'/storage-metadata.csv')
            hbc.file_request(address,'D',copy_directory+'/storage-complete')
            if a.hardware: print(metadata.decode().strip(),flush=True)
        hbc.file_request(address,'D',copy_directory)
        groups={}
        for row in rows:
            group=(row.get('operation','copy'),int(row['buffer_bytes']))
            groups.setdefault(group,[]).append(int(row['bytes'])/1048576/(int(row['microseconds'])/1000000))
        if not a.hardware: print('Dolphin SD transfer correctness verified; emulator timings are not drive speeds',flush=True)
        for (operation,buffer),speeds in (groups.items() if a.hardware else ()):
            print(f'{a.storage_device or "sd"} {operation} {buffer//1024} KiB: median {statistics.median(speeds):.3f} MiB/s ({len(speeds)} verified runs)',flush=True)

    time.sleep(1) # Let the startup fade finish.
    shot('browser.png')
    key('h'); shot('home.png')
    key('la'); shot('settings.png'); key('a'); shot('settings-saved.png')
    key('b'); key('rra'); shot('diagnostics.png') # Back to Settings, then two tabs right.
    key('a'); shot('probes-flushed.png')
    key('h'); shot('browser-restored.png')
    data = b'WiiXplorer HBC-Reborn roundtrip\n'*100
    hbc.put_file(address,remote,data); uploaded = True
    if hbc.get_file(address,remote) != data: raise RuntimeError('File roundtrip differs')
    if a.transfer_bench:
        measurements = []
        fixture_bytes=a.transfer_mib*1024*1024
        seed=b'WiiXplorer-transfer-benchmark!\n'
        compressible=(seed*((fixture_bytes+len(seed)-1)//len(seed)))[:fixture_bytes]
        for label, payload, level in (
            ('random', random.Random(42).randbytes(fixture_bytes), 0),
            ('compressible', compressible, 6)):
            for repeat in range(a.transfer_repeats):
                start_transfer=time.monotonic()
                hbc.put_file(address,remote,payload,level=level)
                upload_seconds=time.monotonic()-start_transfer
                start_transfer=time.monotonic()
                received=hbc.get_file(address,remote,compress=bool(level))
                download_seconds=time.monotonic()-start_transfer
                if received != payload: raise RuntimeError('Benchmark SHA/content mismatch')
                measurements.append({'kind':label, 'repeat':repeat, 'bytes':len(payload),
                    'upload_mib_s':len(payload)/1048576/upload_seconds,
                    'download_mib_s':len(payload)/1048576/download_seconds,
                    'sha256':hashlib.sha256(payload).hexdigest()})
                print('Verified',label,repeat+1,'upload/download MiB/s',
                      round(measurements[-1]['upload_mib_s'],3),
                      round(measurements[-1]['download_mib_s'],3),flush=True)
        # At least 8 MiB must remain to fill large Dolphin host send buffers,
        # even when the timing fixture was shortened for diagnosis.
        if fixture_bytes < 8*1024*1024:
            hbc.put_file(address,remote,random.Random(43).randbytes(8*1024*1024),level=0)
        # Keep a download peer connected without draining its receive window.
        # The app must release its listener through the send watchdog, while
        # this peer is still open; closing it first would not prove the bound.
        with hbc.connect(address) as stalled:
            stalled.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            started=time.monotonic()
            stalled.sendall(hbc.file_header('g',remote,flags=0))
            deadline=started+(20 if a.hardware else 60)
            while True:
                try:
                    if hbc.is_agent(hbc.version(address,timeout=1)): break
                except (OSError,hbc.HBCError): pass
                if time.monotonic() >= deadline:
                    raise RuntimeError('Stalled download held the app listener')
                time.sleep(.25)
            stalled_download_seconds=round(time.monotonic()-started,3)
        # Existing data must survive malformed, truncated, and stalled uploads.
        hbc.put_file(address,remote,data)
        for failure in ('crc', 'short', 'idle', 'oversize'):
            with hbc.connect(address) as conn:
                if failure == 'oversize':
                    conn.sendall(hbc.file_header('p',remote,512*1024*1024+1))
                else:
                    conn.sendall(hbc.file_header('p',remote,4))
                    if failure == 'crc': conn.sendall(struct.pack('>III',4,4,0)+b'bad!')
                    elif failure == 'short':
                        conn.sendall(struct.pack('>III',4,4,zlib.crc32(b'test'))+b't')
                        conn.shutdown(socket.SHUT_WR)
                    # idle: wait for the app's bounded receive timeout.
                started=time.monotonic()
                conn.settimeout(15 if a.hardware else 60)
                try: hbc.recv_reply(conn)
                except socket.timeout:
                    raise RuntimeError('App receive deadline did not reject upload: '+failure)
                except (hbc.HBCError, OSError): pass
                else: raise RuntimeError('Invalid upload accepted: '+failure)
                elapsed=time.monotonic()-started
                print('Rejected',failure,'upload in',round(elapsed,3),'seconds',flush=True)
                if elapsed > (15 if a.hardware else 60): raise RuntimeError('Upload timeout exceeded')
            if hbc.get_file(address,remote) != data: raise RuntimeError('Failed upload replaced destination')
        medians={label:{direction:round(statistics.median(m[direction+'_mib_s'] for m in measurements if m['kind']==label),3)
                       for direction in ('upload','download')} for label in ('random','compressible')}
        (profile/'transfer-benchmark.json').write_text(json.dumps({'measurements':measurements,'median_mib_s':medians,
            'failure_checks':['crc','short','idle','oversize','stalled-download'],
            'stalled_download_seconds':stalled_download_seconds,'passed':True},indent=2))
        print('Transfer benchmark median MiB/s:',json.dumps(medians),flush=True)
    if hbc.status(address).get('app')!='WiiXplorer NG': raise RuntimeError('Controller unexpectedly left WiiXplorer before FTP checks')
    if a.ftp_smoke:
        passive_endpoints=[]
        class SmokeFtp(ftplib.FTP):
            def makepasv(self):
                endpoint=super().makepasv()
                # Record only endpoints; never enable ftplib command tracing/PASS logs.
                passive_endpoints.append({'host':endpoint[0],'port':endpoint[1],
                    'control_peer':self.sock.getpeername(),'control_local':self.sock.getsockname()})
                (profile/'ftp-passive.json').write_text(json.dumps(passive_endpoints,indent=2)+'\n')
                return endpoint
        rejected=ftplib.FTP(timeout=15)
        try:
            rejected.connect(address,ftp_port)
            try: rejected.login(ftp_user,ftp_password+'-invalid')
            except ftplib.error_perm as error:
                if not str(error).startswith('530'): raise RuntimeError('Unexpected FTP authentication rejection')
            else: raise RuntimeError('FTP accepted an incorrect password')
        finally: rejected.close()
        ftp_connection=SmokeFtp(timeout=15)
        ftp_connection.connect(address,ftp_port)
        ftp_connection.login(ftp_user,ftp_password)
        ftp_devices=ftp_connection.nlst()
        if 'sd' not in ftp_devices: raise RuntimeError('Mounted SD missing from FTP root')
        print('FTP mounted devices:', ', '.join(ftp_devices), flush=True)
        ftp_remote='/sd/'+remote.split(':/',1)[1]
        payload=random.Random(42).randbytes(1024*1024)
        hbc.put_file(address,remote,data)
        ftp_connection.storbinary('STOR '+ftp_remote,io.BytesIO(payload),blocksize=64*1024)
        out=bytearray()
        ftp_connection.retrbinary('RETR '+ftp_remote,out.extend,blocksize=64*1024)
        if out!=payload or hbc.get_file(address,remote)!=payload: raise RuntimeError('FTP roundtrip mismatch')
        listing=[]
        ftp_connection.retrlines('LIST /sd',listing.append)
        if not any(remote.split(':/',1)[1] in row for row in listing): raise RuntimeError('FTP LIST missing uploaded SD fixture')
        usb=next((dev for dev in ftp_devices if dev in ('usb1','usb2','usb3','usb4','usb5','usb6','usb7','usb8')),None)
        if usb:
            usb_remote='/'+usb+'/wiixplorer-ftp-smoke-'+profile.name+'-'+secrets.token_hex(8)+'.bin'
            ftp_connection.storbinary('STOR '+usb_remote,io.BytesIO(payload))
            usb_out=bytearray();ftp_connection.retrbinary('RETR '+usb_remote,usb_out.extend)
            usb_listing=[];ftp_connection.retrlines('LIST /'+usb,usb_listing.append)
            if usb_out!=payload or not any(usb_remote.rsplit('/',1)[1] in row for row in usb_listing): raise RuntimeError('FTP USB roundtrip/LIST mismatch')
            ftp_connection.delete(usb_remote)
            print('FTP USB LIST/RETR/STOR passed:',usb,flush=True)
        else: print('FTP USB check skipped: no mounted USB device',flush=True)
        ftp_connection.storbinary('STOR '+ftp_remote,io.BytesIO(b''))
        if hbc.get_file(address,remote)!=b'': raise RuntimeError('Empty FTP upload failed')
        ftp_connection.storbinary('STOR '+ftp_remote,io.BytesIO(b'prefix-old'))
        ftp_connection.storbinary('STOR '+ftp_remote,io.BytesIO(b'new'),rest=7)
        ftp_connection.storbinary('APPE '+ftp_remote,io.BytesIO(b'-append'))
        if hbc.get_file(address,remote)!=b'prefix-new-append': raise RuntimeError('FTP append/resume mismatch')
        hbc.put_file(address,remote,data)
        ftp_data=ftp_connection.transfercmd('STOR '+ftp_remote)
        ftp_data.sendall(b'unfinished')
        started=time.monotonic()
        ftp_connection.sock.settimeout(45 if a.hardware else 90)
        try: ftp_connection.voidresp()
        except ftplib.error_temp as error:
            if not str(error).startswith('426'): raise
        except (EOFError, ConnectionResetError): pass # ftpsrv expires the whole session
        else: raise RuntimeError('Stalled FTP upload accepted')
        ftp_data.close();ftp_data=None
        if hbc.get_file(address,remote)!=data: raise RuntimeError('FTP timeout replaced old destination')
        ftp_connection.close()
        ftp_connection=SmokeFtp(timeout=15);ftp_connection.connect(address,ftp_port)
        ftp_connection.login(ftp_user,ftp_password)
        ftp_data=ftp_connection.transfercmd('STOR '+ftp_remote)
        ftp_data.sendall(b'exit-during-upload')
        print('FTP bad-password rejection, roundtrip, empty, append/resume and idle preservation passed',flush=True)
    else:
        hbc.file_request(address,'D',remote); uploaded = False
    if hbc.status(address).get('app')!='WiiXplorer NG': raise RuntimeError('Controller unexpectedly left WiiXplorer before transfer checks')
    # Fetch while mounted. The subsequent clean exit proves the final flush separately.
    probes = hbc.get_file(address,'sd:/apps/WiiXplorer/probes.csv')
    (profile/'probes.csv').write_bytes(probes)
    try:
        memory_probes=hbc.get_file(address,'sd:/apps/WiiXplorer/memory-probes.csv')
        (profile/'memory-probes.csv').write_bytes(memory_probes)
    except hbc.HBCError as error:
        if error.code != hbc.ENOENT: raise
    key('h') # Also check remote exit while inside the overlay.
    start = time.monotonic()
    hbc.request(address,b'HBCX')
    if a.hardware:
        version = hbc.hbc_wait(address,30)
        (profile/'hbc-after.json').write_text(json.dumps(hbc.status(address),indent=2))
        (profile/'probes.csv').write_bytes(hbc.get_file(address,'sd:/apps/WiiXplorer/probes.csv'))
        if (profile/'memory-probes.csv').exists():
            (profile/'memory-probes.csv').write_bytes(hbc.get_file(address,'sd:/apps/WiiXplorer/memory-probes.csv'))
        if a.ftp_smoke and hbc.get_file(address,remote)!=data: raise RuntimeError('FTP exit replaced old destination')
        print('Returned to HBC:',version,flush=True)
    else:
        while 'WiiXplorer: shutdown cleanup completed' not in (profile/'Logs/dolphin.log').read_text(errors='replace'):
            if time.monotonic()-start>15: raise RuntimeError('Guest teardown did not complete')
            time.sleep(.25)
    with (profile/'probes.csv').open(newline='') as stream:
        rows=list(csv.DictReader(stream))
    if not rows: raise RuntimeError('No probe records')
    if (profile/'memory-probes.csv').exists():
        with (profile/'memory-probes.csv').open(newline='') as stream:
            memory_rows=list(csv.DictReader(stream))
        last_memory={}
        for row in memory_rows:
            if None in row or any(value is None for value in row.values()):
                raise RuntimeError('Incomplete memory probe record')
            if row['kind']=='owner' and int(row['accounting_errors']):
                raise RuntimeError('Memory owner accounting mismatch: '+row['owner'])
            if row['kind']=='owner': last_memory[(row['owner'],row['bank'])]=row
            if row['kind']=='snapshot' and int(row['integrity_errors']):
                raise RuntimeError('Memory snapshot heap integrity failed')
        if a.hardware and any(int(row['live_bytes']) for row in last_memory.values()):
            raise RuntimeError('Tracked buffers remain live after native teardown')
    for row in rows:
        if None in row or any(value is None for value in row.values()):
            raise RuntimeError('Incomplete probe record')
        if row['group'] in ('cpu','gpu') and row['level']=='3' and int(row['value']):
            raise RuntimeError('Heap/GPU integrity check failed')
    result={'file_bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest(),
            'remote_exit_seconds':round(time.monotonic()-start,3), 'ftp_passed':a.ftp_smoke, 'ftp_devices':ftp_devices, 'passed':True}
    (profile/'hbc-smoke.json').write_text(json.dumps(result,indent=2))
    print('Agent overlay, settings/diagnostics buttons, file roundtrip and exit passed',flush=True)
finally:
    if capture_process:
        capture_process.terminate()
        try: capture_process.wait(timeout=5)
        except subprocess.TimeoutExpired: capture_process.kill();capture_process.wait(timeout=5)
    if capture_log: capture_log.close()
    if log_server: log_server.close()
    if ftp_data: ftp_data.close()
    if ftp_connection: ftp_connection.close()
    if not a.hardware and sys.exc_info()[0] is not None:
        try:
            status=hbc.status(address)
            (profile/'failure-status.json').write_text(json.dumps(status,indent=2)+'\n')
            if status.get('app')=='WiiXplorer NG':
                width,height,pixels=hbc.screen(address)
                (profile/'failure.png').write_bytes(hbc.yuyv_png(width,height,pixels))
                hbc.request(address,b'HBCX')
        except (OSError,hbc.HBCError): pass
    if a.hardware:
        # The official client refuses to exit an app that predates this lease.
        if uploaded:
            try: hbc.file_request(address,'D',remote)
            except (OSError,hbc.HBCError): pass
        if sys.exc_info()[0] is not None:
            try:
                (profile/'failure-status.json').write_text(json.dumps(hbc.status(address),indent=2)+'\n')
                width,height,pixels=hbc.screen(address)
                (profile/'failure.png').write_bytes(hbc.yuyv_png(width,height,pixels))
            except (OSError,hbc.HBCError): pass
        hbc.exit_app(address,30)
        hbc.hbc_wait(address,30)
        if log_server: log_server.unregister(address)
        try:
            failure_probes=hbc.get_file(address,'sd:/apps/WiiXplorer/probes.csv')
            (profile/'after-probes.csv').write_bytes(failure_probes)
        except (OSError,hbc.HBCError): pass
        if copy_owned and a.memory_bench:
            for name in ('memory-benchmark.csv','memory-workingset.csv','memory-complete','memory-capacity.csv'):
                try: (profile/('after-'+name)).write_bytes(hbc.get_file(address,copy_directory+'/'+name))
                except (OSError,hbc.HBCError): pass
        archive_cleanup_errors=[]
        if archive_owned:
            try: (profile/'after-archive-results.csv').write_bytes(hbc.get_file(address,archive_transport_directory+'/archive-results.csv'))
            except (OSError,hbc.HBCError): pass
            for relative in sorted(archive_cleanup,key=lambda x:(x.count('/'),x),reverse=True):
                try: hbc.file_request(address,'D',archive_transport_directory+'/'+relative)
                except hbc.HBCError as error:
                    if error.code != hbc.ENOENT: archive_cleanup_errors.append(str(error))
            try: hbc.file_request(address,'D',archive_transport_directory) # Refuse unknown/nonempty leftovers.
            except hbc.HBCError as error:
                if error.code != hbc.ENOENT: archive_cleanup_errors.append(str(error))
        if copy_owned:
            for suffix in ('/media.mth','/media.pdf','/media.jpg','/media-results.csv','/media-complete','/source','/destination','/copy-benchmark.csv','/storage-benchmark.csv','/storage-metadata.csv','/storage-complete','/memory-complete','/memory-benchmark.csv','/memory-workingset.csv','/memory-capacity.csv',''):
                try: hbc.file_request(address,'D',copy_directory+suffix)
                except hbc.HBCError as error:
                    if error.code != hbc.ENOENT: raise
        for remote_config, content in backups.items():
            if content is not None:
                hbc.put_file(address,remote_config,content)
            else:
                try: hbc.file_request(address,'D',remote_config)
                except hbc.HBCError as error:
                    if error.code != hbc.ENOENT: raise
        for directory in reversed(created_dirs):
            hbc.file_request(address,'D',directory) # Empty directories only.
        print('Original SD configuration/probe files restored',flush=True)
        if archive_cleanup_errors:
            raise RuntimeError('Settings restored; owned archive fixtures have retained leftovers: '+ '; '.join(archive_cleanup_errors))
