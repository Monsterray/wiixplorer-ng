#!/usr/bin/env python3
"""Real MD5 code: vectors, empty files, truncated reads and close-failure rejection."""
from pathlib import Path
import os,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='wx-md5-') as directory:
    root=Path(directory)
    code=(ROOT/'source/FileOperations/MD5.c').read_bytes()
    code=code.replace(b'#include "MD5.h"',b'#include "MD5.h"\nextern size_t testRead(void*,size_t,size_t,FILE*);\nextern int testClose(FILE*);\n#define fread testRead\n#define fclose testClose')
    (root/'md5.c').write_bytes(code)
    (root/'test.c').write_text(r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "MD5.h"
int badRead=0,badClose=0;unsigned closed=0;
size_t testRead(void *p,size_t n,size_t count,FILE *f){return badRead ? 0 : fread(p,n,count,f);}
int testClose(FILE *f){++closed;int r=fclose(f);return badClose ? -1 : r;}
int main(){
 unsigned char hash[16];char hex[33];FILE *f=fopen("empty","wb");assert(f);fclose(f);
 assert(MD5fromFile(hash,"empty") && !strcmp(MD5ToString(hash,hex),"D41D8CD98F00B204E9800998ECF8427E"));
 f=fopen("abc","wb");assert(f && fwrite("abc",1,3,f)==3);fclose(f);
 assert(MD5fromFile(hash,"abc") && !strcmp(MD5ToString(hash,hex),"900150983CD24FB0D6963F7D28E17F72"));
 badRead=1;unsigned before=closed;assert(!MD5fromFile(hash,"abc") && closed==before+1);badRead=0;
 badClose=1;assert(!MD5fromFile(hash,"abc"));badClose=0;
 f=fopen("large","wb");assert(f && fseeko(f,((off_t)1<<32),SEEK_SET)==0 && fputc(0,f)!=EOF);fclose(f);
 assert(!MD5fromFile(hash,"large"));
 assert(!MD5fromFile(hash,"missing") && !MD5fromFile(NULL,"abc"));
}
''')
    subprocess.run([os.environ.get('CC','cc'),'-D_GNU_SOURCE','-std=gnu99','-fsanitize=address,undefined','-I'+str(ROOT/'source/FileOperations'),str(root/'md5.c'),str(root/'test.c'),'-o',str(root/'test')],check=True)
    subprocess.run([str(root/'test')],cwd=root,check=True)
print('MD5 files: standard vectors/empty, truncated reads, close failure and cleanup passed')
