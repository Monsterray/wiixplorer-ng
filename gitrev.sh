#!/bin/sh
# Keep the generated version stable so unchanged builds do not recompile it.
set -eu
cd "$(dirname "$0")"
revision=$(git describe --always --dirty --tags 2>/dev/null || printf unknown)
version=$(cat VERSION)
revision="$version ($revision)"
revision=$(printf '%s' "$revision" | sed 's/\\/\\\\/g; s/"/\\"/g')
temporary=$(mktemp)
trap 'rm -f "$temporary"' EXIT HUP INT TERM
printf 'const char *BuildRev(void) { return "%s"; }\n' "$revision" > "$temporary"
if ! cmp -s "$temporary" source/gitrev.c; then
    cp "$temporary" source/gitrev.c
fi
