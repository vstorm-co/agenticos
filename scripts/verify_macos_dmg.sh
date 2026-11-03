#!/bin/bash
# Authenticate a release asset before its checksum enters the trusted Homebrew tap.
set -euo pipefail

pin_lines="$(grep -vE '^[[:space:]]*(#|$)' "$2" || true)"
if ! [[ "$pin_lines" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "A valid publisher certificate pin is required for Homebrew publication." >&2
  exit 1
fi
pinned="$(printf '%s' "$pin_lines" | tr 'A-F' 'a-f')"
work="$(mktemp -d)"
mount="$work/mount"
mkdir "$mount"
cleanup() {
  hdiutil detach "$mount" -quiet || true
  rm -rf "$work"
}
trap cleanup EXIT
hdiutil attach "$1" -mountpoint "$mount" -nobrowse -readonly -quiet
[ -d "$mount/AgenticOS.app" ] || { echo "AgenticOS.app is missing." >&2; exit 1; }
codesign --verify --deep --strict "$mount/AgenticOS.app"
codesign -d --extract-certificates="$work/signer" "$mount/AgenticOS.app"
signer="$(shasum -a 1 "$work/signer0" | cut -d ' ' -f 1)"
if [ "$signer" != "$pinned" ]; then
  echo "The release asset was not signed by the pinned publisher." >&2
  exit 1
fi
