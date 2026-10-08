#!/usr/bin/env bash
# Download, verify and unpack a Blender Linux x64 release for headless CI.
# Usage: install_blender.sh <version e.g. 4.5.14> <dest dir>
# Afterwards <dest dir>/blender is the executable.
set -euo pipefail
VERSION="$1"
DEST="$2"
MAJOR_MINOR="${VERSION%.*}"
TARBALL="blender-${VERSION}-linux-x64.tar.xz"
BASE_URL="https://download.blender.org/release/Blender${MAJOR_MINOR}"

if [ -x "$DEST/blender" ]; then
  echo "Blender $VERSION already present in $DEST" >&2
  exit 0
fi

mkdir -p "$DEST"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "Downloading $BASE_URL/$TARBALL" >&2
curl -fsSL --retry 5 --retry-delay 10 -o "$WORK/$TARBALL" "$BASE_URL/$TARBALL"
curl -fsSL --retry 5 --retry-delay 10 -o "$WORK/sums.sha256" "$BASE_URL/blender-${VERSION}.sha256"
( cd "$WORK" && grep -F "$TARBALL" sums.sha256 | sha256sum -c - )

tar -xJf "$WORK/$TARBALL" -C "$DEST" --strip-components=1
"$DEST/blender" --version | head -1 >&2
