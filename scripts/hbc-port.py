#!/usr/bin/env python3
"""Check the emulator's fixed HBC port without connecting to another app."""
import argparse
import errno
import time
import socket
import sys

def check_port():
    # Route lookup sends no packet. Binding without listen accepts no clients
    # and creates no firewall exception; close before launching Dolphin.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        route.connect(('192.0.2.1', 9))
        address = route.getsockname()[0]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as check:
        check.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:
            check.bind((address, 4299))
        except OSError as error:
            if error.errno == errno.EADDRINUSE:
                raise RuntimeError('HBC port 4299 is occupied; wait for the other emulator/test to finish. No Dolphin was launched.') from error
            raise

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait', type=int, default=0, help='bounded wait for another test, 0..3600 seconds')
    args=parser.parse_args()
    if not 0<=args.wait<=3600: parser.error('--wait must be 0..3600')
    deadline=time.monotonic()+args.wait
    announced=False
    while True:
        try: check_port();break
        except RuntimeError as error:
            if time.monotonic()>=deadline: sys.exit(str(error))
            if not announced: print('Waiting for shared HBC emulator port 4299',flush=True);announced=True
            time.sleep(min(5,deadline-time.monotonic()))
        except OSError as error: sys.exit(str(error))
