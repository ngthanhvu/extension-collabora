#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/oxt/AutoFurigana"
VERSION="$(sed -n 's/.*<version value="\([^"]*\)".*/\1/p' "$SOURCE/description.xml")"
OUTPUT="$ROOT/dist/AutoFurigana-$VERSION.oxt"

mkdir -p "$ROOT/dist"
rm -f "$ROOT"/dist/AutoFurigana-*.oxt
(
  cd "$SOURCE"
  zip -q -r "$OUTPUT" . -x '*/__pycache__/*' '*.pyc'
)
echo "$OUTPUT"
