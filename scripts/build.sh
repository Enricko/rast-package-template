#!/usr/bin/env bash
# Build the example package (static Lua) for the runner's own target.
#
#   scripts/build.sh <target> <out-dir>
#
# Downloads the source release named in package.json, refuses it unless its
# SHA-256 matches, builds static binaries, runs them, and writes a
# reproducible <id>-<version>-<target>.tar.gz whose top directory is stripped
# by RAST (stripComponents 1), so executables live at bin/lua and bin/luac.
set -euo pipefail

TARGET=$1 OUT=$2
case "$TARGET" in
  linux-x86_64) ARCH=x86_64 ;;
  linux-aarch64) ARCH=aarch64 ;;
  *) echo "unknown target $TARGET" >&2; exit 1 ;;
esac
[ "$(uname -m)" = "$ARCH" ] || { echo "build $TARGET on a native $ARCH machine (got $(uname -m))" >&2; exit 1; }

HERE=$(cd "$(dirname "$0")/.." && pwd)
# Read the template without Python (the tooling is Rust or shell only).
json_first() {
  sed -n "s/^[[:space:]]*\"$1\": \"\([^\"]*\)\".*/\1/p" "$HERE/package.json" | head -n 1
}
ID=$(json_first id)
VERSION=$(json_first version)
read -r URL SHA < <(awk '
  /"source"[[:space:]]*:/ { in_source = 1; next }
  in_source && /"url"[[:space:]]*:/ {
    line = $0; sub(/.*"url"[[:space:]]*:[[:space:]]*"/, "", line); sub(/".*/, "", line); url = line
  }
  in_source && /"sha256"[[:space:]]*:/ {
    line = $0; sub(/.*"sha256"[[:space:]]*:[[:space:]]*"/, "", line); sub(/".*/, "", line)
    print url, line; exit
  }
' "$HERE/package.json")
[ -n "$ID" ] && [ -n "$VERSION" ] && [ -n "$URL" ] && [ -n "$SHA" ] || {
  echo "cannot read id/version/source.url/source.sha256 from package.json" >&2; exit 1;
}

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
curl -fsSL --proto '=https' --tlsv1.2 -o "$WORK/src.tar.gz" "$URL"
echo "$SHA  $WORK/src.tar.gz" | sha256sum -c -
tar -xzf "$WORK/src.tar.gz" -C "$WORK"
SRC="$WORK/lua-$VERSION"

# posix: no dlopen, so a fully static link works; no readline dependency.
make -C "$SRC" -j"$(nproc)" posix MYLDFLAGS=-static >/dev/null
for exe in lua luac; do
  file "$SRC/src/$exe" | grep -q "statically linked" || { echo "$exe is not static" >&2; exit 1; }
done
"$SRC/src/lua" -v | grep -F "Lua $VERSION" >/dev/null

PKG="$ID-$VERSION"
STAGE="$WORK/stage/$PKG"
mkdir -p "$STAGE/bin" "$STAGE/share/doc"
install -m 0755 "$SRC/src/lua" "$SRC/src/luac" "$STAGE/bin/"
strip "$STAGE/bin/lua" "$STAGE/bin/luac"
cp "$SRC/README" "$STAGE/share/doc/README"
# The MIT license text is in lua.h; ship it next to the binaries.
sed -n '/Copyright (C)/,/^\*\//p' "$SRC/src/lua.h" > "$STAGE/share/doc/LICENSE"
cat > "$STAGE/BUILDINFO.json" <<JSON
{
  "id": "$ID",
  "version": "$VERSION",
  "target": "$TARGET",
  "source": "$URL",
  "sourceSha256": "$SHA",
  "workflowRun": "${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-local}/actions/runs/${GITHUB_RUN_ID:-0}"
}
JSON

mkdir -p "$OUT"
ARCHIVE="$OUT/$PKG-$TARGET.tar.gz"
tar --sort=name --owner=0 --group=0 --numeric-owner --mtime=@0 -C "$WORK/stage" -cf - "$PKG" | gzip -n -9 > "$ARCHIVE"
sha256sum "$ARCHIVE"
echo "archive=$ARCHIVE" >> "${GITHUB_OUTPUT:-/dev/null}"
