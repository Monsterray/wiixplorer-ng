#!/usr/bin/env python3
"""Rebuild the original Wii ports locally; never install into the shared SDK."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT / '.deps'
SDK = Path(os.environ.get('DEVKITPRO', '/opt/devkitpro'))
PPC = Path(os.environ.get('DEVKITPPC', SDK / 'devkitPPC'))
PREFIX = DEPS / 'prefix'
ARCHIVE_BASE = 'https://storage.googleapis.com/google-code-archive-source/v2/code.google.com/'
DOWNLOADS = [
    ('wiixplorer.zip', ARCHIVE_BASE + 'wiixplorer/source-archive.zip',
     '9abdc9acfe95d5fc0669bb2f258ce422c692224580ef4d8e0077809823254a8e'),
    ('libntfs-wii.zip', ARCHIVE_BASE + 'libntfs-wii/source-archive.zip',
     '51170793f46b6532f691896b04b2fa7b009e65ef2ba09241bac8a5c3bcc281ca'),
    ('libext2fs-wii.zip', ARCHIVE_BASE + 'libext2fs-wii/source-archive.zip',
     'eeb828cea6056bd1a90b2d4c909d501078d2886da67eb68c5c21bda3cbac04f3'),
    ('libnfs-wii.zip', ARCHIVE_BASE + 'libnfs-wii/source-archive.zip',
     '8f557356516d3a65331d55a78e5c632ff6e853986e164089956be12e3e55e2c2'),
    ('ogg.tar.xz', 'https://downloads.xiph.org/releases/ogg/libogg-1.3.6.tar.xz',
     '5c8253428e181840cd20d41f3ca16557a9cc04bad4a3d04cce84808677fa1061'),
    ('tremor.tar.gz', 'https://gitlab.xiph.org/xiph/tremor/-/archive/'
     '820fb3237ea81af44c9cc468c8b4e20128e3e5ad/'
     'tremor-820fb3237ea81af44c9cc468c8b4e20128e3e5ad.tar.gz',
     '3974455fe776a41615f60e05c85733c1bb78bff310794cbb0236f8af4b44f583'),
]


def prepare_sources():
    cache = DEPS / 'downloads'
    source = DEPS / 'src'
    cache.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    for name, url, expected in DOWNLOADS:
        archive = cache / name
        if not archive.exists():
            subprocess.run(['curl', '--fail', '--location', '--retry', '2', url,
                            '--output', str(archive)], check=True)
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f'Checksum mismatch for {archive}; delete it and retry.')
        marker = source / (name + '.extracted')
        if marker.exists():
            continue
        if name.endswith('.zip'):
            with zipfile.ZipFile(archive) as z:
                for entry in z.infolist():
                    path = Path(entry.filename)
                    if path.is_absolute() or '..' in path.parts:
                        raise SystemExit('Unsafe archive member: ' + entry.filename)
                    if '.svn' in path.parts:
                        continue
                    if name == 'wiixplorer.zip' and not entry.filename.startswith('wiixplorer/branches/libs/'):
                        continue
                    z.extract(entry, source)
        else:
            with tarfile.open(archive) as t:
                # The pinned Xiph archives contain ordinary source files only.
                for entry in t.getmembers():
                    path = Path(entry.name)
                    if path.is_absolute() or '..' in path.parts or entry.issym() or entry.islnk():
                        raise SystemExit('Unsafe archive member: ' + entry.name)
                t.extractall(source)
        marker.touch()


def build(name, original, source_dir='source', defines=(), headers=None, files=None):
    patch = ROOT / 'scripts' / 'patches' / (name + '.patch')
    fingerprint = hashlib.sha256(Path(__file__).read_bytes() +
                                 (patch.read_bytes() if patch.exists() else b'') +
                                 subprocess.check_output([str(PPC / 'bin/powerpc-eabi-gcc'), '--version'])).hexdigest()
    work = DEPS / 'work' / name
    marker = work / '.recipe'
    if not marker.exists() or marker.read_text() != fingerprint:
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(original, work)
        for source in work.rglob("*"):
            if source.suffix in (".c", ".cpp", ".h", ".hpp"):
                source.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
        if patch.exists():
            subprocess.run(['patch', '-p1', '-i', str(patch)], cwd=work, check=True)
        marker.write_text(fingerprint)
    sources = work / source_dir
    include = PREFIX / 'include'
    include.mkdir(parents=True, exist_ok=True)
    (PREFIX / 'lib').mkdir(parents=True, exist_ok=True)
    if name == 'ogg':
        (sources / 'ogg/config_types.h').write_text(
            '#include <stdint.h>\ntypedef int16_t ogg_int16_t;\ntypedef uint16_t ogg_uint16_t;\n'
            'typedef int32_t ogg_int32_t;\ntypedef uint32_t ogg_uint32_t;\n'
            'typedef int64_t ogg_int64_t;\ntypedef uint64_t ogg_uint64_t;\n')
    for header_dir, destination in headers or [(source_dir, '')]:
        dest = include / destination
        dest.mkdir(parents=True, exist_ok=True)
        for header in (work / header_dir).glob('*.h'):
            shutil.copy2(header, dest / header.name)
        for header in (work / header_dir).glob('*.hpp'):
            shutil.copy2(header, dest / header.name)
    inputs = [work / f for f in files] if files else sorted(sources.glob('*.c')) + sorted(sources.glob('*.cpp'))
    objects_dir = work / 'objects'
    objects_dir.mkdir(exist_ok=True)
    flags = ['-DGEKKO', '-mrvl', '-mcpu=750', '-meabi', '-mhard-float', '-O2', '-g',
             '-I' + str(include), '-I' + str(SDK / 'libogc/include'),
             '-I' + str(SDK / 'portlibs/ppc/include'),
             '-I' + str(SDK / 'portlibs/ppc/include/freetype2'),
             '-I' + str(work / 'include'), '-I' + str(sources)] + ['-D' + d for d in defines]
    # These EXT headers deliberately use the GNU89 extern-inline convention.
    if name == 'ext2fs':
        flags.append('-fgnu89-inline')

    def compile_one(path):
        obj = objects_dir / (path.stem + '.o')
        if obj.exists() and obj.stat().st_mtime >= path.stat().st_mtime:
            return obj, ''
        cxx = path.suffix == '.cpp'
        compiler = PPC / ('bin/powerpc-eabi-g++' if cxx else 'bin/powerpc-eabi-gcc')
        result = subprocess.run([str(compiler), '-std=gnu++98' if cxx else '-std=gnu99',
                                 *flags, '-c', str(path), '-o', str(obj)],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return obj, result.stdout + result.stderr

    print('Building ' + name, flush=True)
    with ThreadPoolExecutor(max_workers=int(os.environ.get('JOBS', '8'))) as pool:
        results = list(pool.map(compile_one, inputs))
    (work / 'build.log').write_text(''.join(log for _, log in results))
    archive = PREFIX / 'lib' / ('lib' + name + '.a')
    if archive.exists():
        archive.unlink()
    subprocess.run([str(PPC / 'bin/powerpc-eabi-ar'), 'rcs', str(archive),
                    *[str(obj) for obj, _ in results]], check=True)


def main():
    prepare_sources()
    base = DEPS / 'src/wiixplorer/branches/libs'
    build('jpeg', base / 'libjpeg', defines=['HAVE_CONFIG_H'])
    build('tiff', base / 'libtiff', defines=['HAVE_CONFIG_H', 'HAVE_LIBZ', 'HAVE_LIBJPEG'])
    build('gd', base / 'libgd', defines=['HAVE_CONFIG_H'])
    build('zip', base / 'libzip', defines=['HAVE_LIBZ'], headers=[('source', 'zip')])
    build('sevenzip', base / 'lib7zip', defines=['_7ZIP_ST', '__BIG_ENDIAN__'], headers=[('source', 'sevenzip')])
    build('unrar', base / 'libunrar', source_dir='.', defines=['BIG_ENDIAN', 'SILENT', 'UNRAR'], headers=[('.', 'libunrar')],
          files=[x + '.cpp' for x in ('rar strlist strfn pathfn savepos smallfn global file filefn filcreat '
                 'archive arcread unicode system isnt crypt crc rawread encname resource match timefn rdwrfn '
                 'consio options ulinks errhnd rarvm rijndael getbits sha1 extinfo extract volume list find '
                 'unpack cmddata filestr recvol rs scantree').split()])
    build('mupdf', base / 'libmupdf', defines=['HAVE_LIBZ', 'NOCJK'], headers=[('source', 'mupdf')])
    for name, project, defines in [('ntfs', 'libntfs-wii', ['HAVE_CONFIG_H']),
                                   ('ext2fs', 'libext2fs-wii', ['WORDS_BIGENDIAN']),
                                   ('nfs', 'libnfs-wii', ['WORDS_BIGENDIAN'])]:
        build(name, DEPS / 'src' / project / 'trunk', defines=defines, headers=[('include', '')])
    build('ogg', DEPS / 'src/libogg-1.3.6', source_dir='include', headers=[('include/ogg', 'ogg')],
          files=['src/bitwise.c', 'src/framing.c'])
    build('vorbisidec', DEPS / 'src/tremor-820fb3237ea81af44c9cc468c8b4e20128e3e5ad', source_dir='.', headers=[('.', 'tremor')],
          files=[x + '.c' for x in ('mdct block window synthesis info floor1 floor0 vorbisfile res012 '
                                    'mapping0 registry codebook sharedbook').split()])
    print('Dependencies ready in .deps/prefix')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
