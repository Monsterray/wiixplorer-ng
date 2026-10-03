#!/usr/bin/env python3
"""Run the official client from our pinned HBC-Reborn dependency."""
from pathlib import Path
import runpy
import sys
client = Path(__file__).resolve().parents[1]/'.deps/prefix/bin/hbc.py'
if not client.exists():
    sys.exit('Build the SDK first: python3 scripts/build-hbc-agent.py')
runpy.run_path(str(client), run_name='__main__')
