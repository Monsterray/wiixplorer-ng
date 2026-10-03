#!/usr/bin/env bash
# Resource generator compatibility entry point (original script by Dimok).
set -euo pipefail
root=$(cd "$(dirname "$0")" && pwd)
exec python3 "$root/scripts/resource-list.py" "${1:-$root/build/release/Memory/filelist.h}"
