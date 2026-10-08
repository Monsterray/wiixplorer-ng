#!/usr/bin/env bash
# Create an isolated, disposable SD/profile and retain the matching debug files.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
prepare_only=false
debugger=false
seconds=0
capture=false
smoke_frames=
gdb_port=
config_seed=
sd_image=
bench=
build_config=${CONFIG:-release}
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prepare-only) prepare_only=true ;;
        --debug) debugger=true ;;
        --capture) capture=true ;;
        --smoke-frames) shift; smoke_frames=${1:?frame count required} ;;
        --build) shift; build_config=${1:?debug or release required} ;;
        --gdb-port) shift; gdb_port=${1:?port required} ;;
        --config-seed) shift; config_seed=${1:?configuration file required} ;;
        --bench) shift; bench=${1:?archive, memory, storage, copy, media or features required} ;;
        --sd-image) shift; sd_image=${1:?image required} ;;
        --seconds) shift; seconds=${1:?seconds required} ;;
        --status|--stop|--force-stop|--stop-all) exec python3 "$root/scripts/dolphin-process.py" "$1" ;;
        *) printf 'Usage: %s [--build debug|release] [--prepare-only] [--debug] [--capture] [--seconds N] [--smoke-frames N] [--gdb-port PORT] [--bench archive|memory|storage|copy|media|features] [--sd-image PATH] [--config-seed PATH] [--status|--stop|--force-stop|--stop-all]\n' "$0" >&2; exit 2 ;;
    esac
    shift
done
case "$build_config" in debug|release) ;; *) printf 'Build must be debug or release.\n' >&2; exit 2 ;; esac
if [ -n "$smoke_frames" ]; then
    if [ "$build_config" != debug ]; then printf 'Smoke frames require a debug build.\n' >&2; exit 2; fi
    python3 -c 'import sys; assert 1 <= int(sys.argv[1]) <= 36000' "$smoke_frames"
fi
build_dir="$root/build/$build_config"
if [ ! -f "$build_dir/boot.dol" ]; then
    printf 'Build with make %s first.\n' "$build_config" >&2
    exit 1
fi
mkdir -p "$root/build"
profile=$(mktemp -d "$root/build/dolphin.XXXXXX")
mkdir -p "$profile/Config" "$profile/artifacts" \
    "$profile/Load/WiiSDSync/apps/WiiXplorer" \
    "$profile/Load/WiiSDSync/wiixplorer-test/source" \
    "$profile/Load/WiiSDSync/wiixplorer-test/destination"
for file in boot.dol boot.elf boot.map probe-config.h build-info.json; do
    if [ -f "$build_dir/$file" ]; then cp "$build_dir/$file" "$profile/artifacts/$file"; fi
done
cp "$root/.deps/prefix/hbc-agent.json" "$profile/artifacts/hbc-agent.json"
if [ -n "$sd_image" ]; then cp "$sd_image" "$profile/Load/WiiSD.raw"; fi
if [ -n "$smoke_frames" ]; then
    if [ -n "$sd_image" ]; then printf 'Seed smoke-frames.txt in the raw image before using --sd-image.\n' >&2; exit 2; fi
    printf '%s\n' "$smoke_frames" > "$profile/Load/WiiSDSync/apps/WiiXplorer/smoke-frames.txt"
fi
printf 'BootIOS = 58\n' > "$profile/Load/WiiSDSync/apps/WiiXplorer/WiiXplorer.cfg"
if [ -n "$config_seed" ]; then cp "$config_seed" "$profile/Load/WiiSDSync/apps/WiiXplorer/WiiXplorer.cfg"; fi
if [ -n "$bench" ]; then
    if [ "$build_config" != debug ] || [ -n "$sd_image" ]; then printf 'Bench fixtures require a debug folder-sync run.\n' >&2; exit 2; fi
    case "$bench" in
        archive)
            python3 "$root/scripts/archive-fixtures.py" "$profile/Load/WiiSDSync/wiixplorer-archive-$(basename "$profile")"
            printf '%s\n' "--archive-check=sd:/wiixplorer-archive-$(basename "$profile")" > "$profile/Load/WiiSDSync/apps/WiiXplorer/bench.cfg" ;;
        memory|storage|copy|media|features)
            printf '%s\n' "--$bench-bench=sd:/wiixplorer-copy-$(basename "$profile")" > "$profile/Load/WiiSDSync/apps/WiiXplorer/bench.cfg" ;;
        *) printf 'Bench must be archive, memory, storage, copy, media or features.\n' >&2; exit 2 ;;
    esac
    printf '%s\n' "$bench" > "$profile/bench.txt"
fi
printf 'WiiXplorer disposable test file\n' > "$profile/Load/WiiSDSync/wiixplorer-test/source/example.txt"
printf 'Existing destination\n' > "$profile/Load/WiiSDSync/wiixplorer-test/destination/example.txt"
# Copy only a controller mapping; leave personal NAND/SD and other settings alone.
mapping=${DOLPHIN_WIIMOTE_CONFIG:-}
if [ -z "$mapping" ]; then
    case "$(uname -s)" in
        Darwin) mapping="$HOME/Library/Application Support/Dolphin/Config/WiimoteNew.ini" ;;
        MINGW*|MSYS*|CYGWIN*) mapping="${APPDATA:-}/Dolphin Emulator/Config/WiimoteNew.ini" ;;
        *) mapping="${XDG_CONFIG_HOME:-$HOME/.config}/dolphin-emu/WiimoteNew.ini" ;;
    esac
fi
if [ -f "$mapping" ]; then cp "$mapping" "$profile/Config/WiimoteNew.ini"; fi
python3 - "$profile/artifacts" <<'PY'
import hashlib
from pathlib import Path
import subprocess
import sys
folder = Path(sys.argv[1])
lines = [hashlib.sha256(f.read_bytes()).hexdigest() + '  ' + f.name
         for f in sorted(folder.iterdir()) if f.is_file()]
(folder / 'SHA256SUMS').write_text('\n'.join(lines) + '\n')
revision = subprocess.run(['git', 'describe', '--always', '--dirty', '--tags'],
                          capture_output=True, text=True)
(folder / 'revision.txt').write_text(revision.stdout.strip() + '\n')
PY
printed_profile="$profile"
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) printed_profile=$(cygpath -w "$profile") ;; esac
printf 'Dolphin profile, frozen build, and logs: %s\n' "$printed_profile"
if ! "$prepare_only"; then python3 "$root/scripts/hbc-port.py"; fi
boot="$profile/artifacts/boot.dol"
# Native Windows Dolphin expects Windows paths; the devkitPro shell uses POSIX paths.
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) boot=$(cygpath -w "$boot"); profile=$(cygpath -w "$profile") ;;
esac
args=(-e "$boot" -u "$profile"
    -C Dolphin.Core.MMU=True -C Dolphin.Core.OverrideBootIOS=58
    -C Dolphin.Core.CPUThread=False -C Dolphin.Core.WiiSDCard=True
    -C Dolphin.Core.WiiSDCardAllowWrites=True -C Dolphin.Core.WiiSDCardEnableFolderSync=True
    -C Graphics.Hacks.XFBToTextureEnable=False
    -C Graphics.Hacks.EFBAccessEnable=True
    -C Dolphin.Interface.UsePanicHandlers=False
    -C Dolphin.Analytics.PermissionAsked=True -C Dolphin.Analytics.Enabled=False
    -C Dolphin.Interface.ConfirmStop=False -C Logger.Options.WriteToFile=True
    -C Logger.Logs.OSREPORT=True -C Logger.Logs.CONSOLE=True
    -C Logger.Logs.PowerPC=True -C Logger.Logs.JIT=True
    -C Logger.Options.Verbosity=4 -C Logger.Logs.MASTER=True -C Logger.Logs.BOOT=True)
if "$debugger"; then args+=(-d); else args+=(-b); fi
if [ -n "$gdb_port" ]; then
    python3 -c 'import sys; assert 1024 <= int(sys.argv[1]) <= 65535' "$gdb_port"
    args+=(-C "Dolphin.General.GDBPort=$gdb_port")
fi
if [ -n "$sd_image" ]; then args+=(-C Dolphin.Core.WiiSDCardEnableFolderSync=False); fi
# Metal drops textured sprites intermittently on the tested macOS Dolphin version.
if [ "$(uname -s)" = Darwin ]; then args+=(-C "Dolphin.Core.GFXBackend=${DOLPHIN_BACKEND:-OGL}");
elif [ -n "${DOLPHIN_BACKEND:-}" ]; then args+=(-C "Dolphin.Core.GFXBackend=$DOLPHIN_BACKEND"); fi
if "$capture"; then args+=(-C Dolphin.Movie.DumpFrames=True -C Graphics.Settings.DumpFramesAsImages=True); fi
if [ "$(uname -s)" = Darwin ] && [ -z "${DOLPHIN_EXE:-}" ]; then
    launch=(open -n -a "${DOLPHIN_APP:-/Applications/Dolphin.app}" --args "${args[@]}")
else
    launch=("${DOLPHIN_EXE:-dolphin-emu}" "${args[@]}")
fi
if "$prepare_only"; then
    python3 - "$profile" "${launch[@]}" <<'PY_COMMAND'
import json, sys
from pathlib import Path
(Path(sys.argv[1])/'launch-command.json').write_text(json.dumps(sys.argv[2:])+'\n')
PY_COMMAND
    exit 0
fi
python3 "$root/scripts/dolphin-process.py" --seconds "$seconds" "$profile" "${launch[@]}"
