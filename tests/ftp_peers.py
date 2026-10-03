#!/usr/bin/env python3
"""Exercise production FTP PORT validation against third-party data targets."""
from pathlib import Path
import os,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'source/FTPOperations/ftpii/ftp.c').read_text()
start=source.index('static s32 ftp_PORT(');end=source.index('{',start)+1;depth=1
while depth:
    depth+=(source[end]=='{')-(source[end]=='}');end+=1
code=r'''
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <arpa/inet.h>
using s32=int32_t;using u32=uint32_t;using u16=uint16_t;
struct client_t{sockaddr_in address;};
s32 write_reply(client_t*,u16 code,const char*){return code;}
void close_passive_socket(client_t*){}
#define gxprintf(...) ((void)0)
'''+source[start:end]+r'''
int main(){client_t client={};inet_aton("192.168.1.20",&client.address.sin_addr);
 auto check=[&](const char *text,int code){assert(ftp_PORT(&client,const_cast<char*>(text))==code);};
 check("192,168,1,21,39,16",501);check("192,168,1,20,0,0",501);
 check("192,168,1,20,999,1",501);check("999,168,1,20,39,16",501);
 check("192,168,1,20,39,16",200);assert(ntohs(client.address.sin_port)==10000);
 check("192,168,1,21,39,16",501);assert(ntohs(client.address.sin_port)==10000);
}
'''
with tempfile.TemporaryDirectory(prefix='wx-ftp-peers-') as directory:
    tmp=Path(directory);(tmp/'test.cpp').write_text(code)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++11','-fsanitize=address,undefined',str(tmp/'test.cpp'),'-o',str(tmp/'test')],check=True)
    subprocess.run([str(tmp/'test')],check=True,timeout=10)
print('FTP peers: invalid octets, zero port and third-party targets rejected')
