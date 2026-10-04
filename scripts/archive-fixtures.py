#!/usr/bin/env python3
"""Generate deterministic native archive fixtures; requires a host 7z command."""
from pathlib import Path
import struct,zipfile,zlib,subprocess,tempfile,shutil,binascii,hashlib

def generate(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);rows=[]
    payload=b'WiiXplorer archive fixture\n'*5000
    def case(name,success,count,member='payload',data=payload):
        rows.append(f'{name} {int(success)} {count} {member} {len(data)} {zlib.crc32(data):08x}\n')
    def zipcase(name,names):
        with zipfile.ZipFile(root/name,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for n,d in names:z.writestr(n,d)
    zipcase('good.zip',[('payload',payload),('zero',b''),('empty/',b'')]);case('good.zip',True,3)
    with zipfile.ZipFile(root/'crc.zip','w',compression=zipfile.ZIP_STORED) as z:z.writestr('payload',payload)
    data=bytearray((root/'crc.zip').read_bytes());offset=30+struct.unpack_from('<H',data,26)[0]+struct.unpack_from('<H',data,28)[0];data[offset]^=1;(root/'crc.zip').write_bytes(data);case('crc.zip',False,1)
    (root/'short.zip').write_bytes(data[:len(data)//2]);case('short.zip',False,0)
    for name,entry in [('parent.zip','../escape'),('device.zip','sd:/escape'),('backslash.zip','a\\..\\escape'),('absolute.zip','/escape'),('deep.zip','d/'*33+'payload'),('long.zip','a'*768),('control.zip','a\x01b')]:
        zipcase(name,[(entry,payload)]);case(name,False,0)
    with zipfile.ZipFile(root/'link.zip','w') as z:
        info=zipfile.ZipInfo('payload');info.create_system=3;info.external_attr=0o120777<<16;z.writestr(info,'../escape')
    case('link.zip',False,0)
    size=bytearray((root/'good.zip').read_bytes());central=size.index(b'PK\x01\x02');struct.pack_into('<I',size,central+24,0xffffffff);struct.pack_into('<I',size,22,0xffffffff);(root/'size32.zip').write_bytes(size);case('size32.zip',False,0)
    zipcase('empty.zip',[]);case('empty.zip',True,0,data=b'original')
    seven=shutil.which('7z')
    if not seven:raise RuntimeError('Install a host 7z command for real SDK fixtures')
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp);(tmp/'aaa').write_bytes(b'A'*8192);(tmp/'payload').write_bytes(payload);(tmp/'zero').touch();(tmp/'empty').mkdir()
        subprocess.run([seven,'a','-t7z','-ms=on','-mx=5',str((root/'good.7z').resolve()),'aaa','payload','zero','empty'],cwd=tmp,check=True,stdout=subprocess.DEVNULL);case('good.7z',True,4)
        (tmp/'payload').write_bytes(b'Z'*(17*1024*1024));subprocess.run([seven,'a','-t7z','-ms=on','-mx=5',str((root/'budget.7z').resolve()),'payload'],cwd=tmp,check=True,stdout=subprocess.DEVNULL);case('budget.7z',False,1)
    def header(kind,flags,body=b''):
        body=struct.pack('<BHH',kind,flags,7+len(body))+body
        return struct.pack('<H',zlib.crc32(body)&65535)+body
    body=struct.pack('<IIBIIBBHI',len(payload),len(payload),3,zlib.crc32(payload),0x50210000,20,0x30,7,0o100644)+b'payload'
    rar=b'Rar!\x1a\x07\x00'+header(0x73,0,b'\0'*6)+header(0x74,0x8000,body)+payload+header(0x7b,0)
    (root/'good.rar').write_bytes(rar);case('good.rar',True,1)
    bad=bytearray(rar);bad[7]^=1;(root/'header.rar').write_bytes(bad);case('header.rar',False,0)
    bad=bytearray(rar);bad[-8]^=1;(root/'crc.rar').write_bytes(bad);case('crc.rar',False,1)
    # NG derivative: keep the first independent member of the pinned upstream
    # fixture, excluding its links/other members. Original .uu sources/notices
    # remain unchanged under tests/fixtures/rar.
    fixture_root=Path(__file__).resolve().parents[1]/'tests/fixtures/rar'
    for mode,digest in [('normal','1c36a76e84bf08d1fdf7597b43737fa174a0813bf2715bf181fd3afb6f6f1f11'),('best','0f50ec35cac7e60e857b13e4ffb4c679ea3bfc602bb7065d69e47aa9db5c3170')]:
        encoded=(fixture_root/(mode+'.rar.uu')).read_bytes()
        if hashlib.sha256(encoded).hexdigest()!=digest:raise RuntimeError('Upstream RAR fixture checksum mismatch')
        lines=encoded.splitlines();begin=next(i for i,l in enumerate(lines) if l.startswith(b'begin '));decoded=b''
        for line in lines[begin+1:]:
            if line==b'end':break
            decoded+=binascii.a2b_uu(line)
        pos=7
        while pos+7<=len(decoded):
            kind,flags,size=struct.unpack_from('<BHH',decoded,pos+2)
            if size<7 or pos+size>len(decoded):raise RuntimeError('Invalid pinned fixture header')
            if kind==0x74:
                packed,unpacked=struct.unpack_from('<II',decoded,pos+7)
                if flags&0x10 or pos+size+packed>len(decoded) or unpacked!=20111:raise RuntimeError('Unexpected dependent fixture')
                (root/(mode+'.rar')).write_bytes(decoded[:pos+size+packed]+header(0x7b,0))
                rows.append(mode+('.rar 1 1 LibarchiveAddingTest.html 20111 5e05a663\n' if mode=='normal' else '.rar 0 1 LibarchiveAddingTest.html 20111 5e05a663\n'))
                break
            pos+=size
        else:raise RuntimeError('No independent RAR fixture member')
    def put32(v,p,n):struct.pack_into('>I',v,p,n)
    def put16(v,p,n):struct.pack_into('>H',v,p,n)
    u=bytearray(128)
    for p,n in {0:0x55aa382d,4:32,8:43,12:96,32:0x01000000,40:3,44:0x01000001,48:0,52:3,56:3,60:96,64:3}.items():put32(u,p,n)
    u[68:73]=b'\0d\0f\0';u[96:99]=b'abc';(root/'good.u8').write_bytes(u);case('good.u8',True,2,'d/f',b'abc')
    raw=bytes(u);lz=b'LZ77'+bytes((0x10,len(raw)&255,(len(raw)>>8)&255,(len(raw)>>16)&255))+b''.join(b'\0'+raw[i:i+8] for i in range(0,len(raw),8))
    (root/'good.lz77').write_bytes(b'IMD5'+b'\0'*28+lz);case('good.lz77',True,2,'d/f',b'abc')
    (root/'short.lz77').write_bytes(b'IMD5'+b'\0'*28+lz[:-10]);case('short.lz77',False,0,'d/f')
    put32(u,60,0xffffffff);(root/'bad.u8').write_bytes(u);case('bad.u8',False,0,'d/f')
    r=bytearray(132);r[:4]=b'RARC'
    for p,n in {4:132,12:96,32:1,36:32,40:1,44:48,48:8,52:68,68:0,76:0,88:0,92:3}.items():put32(r,p,n)
    r[64:68]=b'ROOT';put16(r,74,1);put16(r,84,0x100);put16(r,86,5);r[100:107]=b'root\0f\0';r[128:131]=b'abc'
    (root/'good.rarc').write_bytes(r);case('good.rarc',True,2,'root/f',b'abc')
    cycle=bytearray(r);put16(cycle,80,0xffff);put16(cycle,84,0x200);put32(cycle,88,0);(root/'cycle.rarc').write_bytes(cycle);case('cycle.rarc',False,0,'f')
    put32(r,88,0xffffffff);(root/'bad.rarc').write_bytes(r);case('bad.rarc',False,0,'f')
    # A real Yaz0 wrapper using literal groups exercises the source-length path.
    raw=(root/'good.rarc').read_bytes();yaz=b'Yaz0'+struct.pack('>I',len(raw))+b'\0'*8
    yaz+=b''.join(b'\xff'+raw[i:i+8] for i in range(0,len(raw),8));(root/'good.yaz0').write_bytes(yaz);case('good.yaz0',True,2,'root/f',b'abc')
    (root/'short.yaz0').write_bytes(yaz[:-3]);case('short.yaz0',False,0,'f')
    (root/'manifest').write_text(''.join(rows))
    return rows

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);args=parser.parse_args()
    print(f'Generated {len(generate(args.output))} native cases in {args.output}')
