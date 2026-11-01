#!/usr/bin/env bash
# Install the AgenticOS desktop app on macOS without the "Apple could not verify"
# dialog. The releases are not notarized (no Apple Developer account), so a DMG
# downloaded in a browser carries the quarantine flag and Gatekeeper refuses it.
# This script downloads the same DMG, checks it against the SHA-256 published in
# the release's own `agenticos.rb`, copies the app to /Applications and clears the
# flag from that one app. `AGENTICOS_INSTALL_DIR` installs somewhere other than
# /Applications, for example `~/Applications`. Nothing else on the system is touched.
#
#   curl -fsSL https://raw.githubusercontent.com/vstorm-co/agenticos/main/scripts/install_macos.sh | bash
#   ... | bash -s -- v1.33.2     # a specific release
set -euo pipefail

repo="vstorm-co/agenticos"
pin_url="${AGENTICOS_SIGNING_IDENTITY_URL:-https://raw.githubusercontent.com/$repo/main/scripts/macos_signing_identity.txt}"
tag="${1:-}"
dest="${AGENTICOS_INSTALL_DIR:-/Applications}"

[ "$(uname -s)" = "Darwin" ] || { echo "This installer is for macOS." >&2; exit 1; }
case "$(uname -m)" in
  arm64) arch="aarch64" ;;
  x86_64) arch="x64" ;;
  *) echo "Unsupported CPU: $(uname -m)" >&2; exit 1 ;;
esac

if [ -z "$tag" ]; then
  tag="$(curl -fsSL "https://api.github.com/repos/$repo/releases/latest" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1)"
fi
case "$tag" in
  v1.*) ;;
  *) echo "Unexpected release tag: '$tag'" >&2; exit 1 ;;
esac

base="https://github.com/$repo/releases/download/$tag"
work="$(mktemp -d)"
mount=""
cleanup() {
  [ -z "$mount" ] || hdiutil detach "$mount" -quiet || true
  rm -rf "$work"
}
trap cleanup EXIT

dmg="AgenticOS_${tag#v}_${arch}.dmg"
echo "Downloading $dmg ($tag)..."
curl -fL --progress-bar -o "$work/$dmg" "$base/$dmg"
curl -fsSL -o "$work/agenticos.rb" "$base/agenticos.rb"

# The cask lists one sha256 per architecture, in on_arm then on_intel order.
if [ "$arch" = "aarch64" ]; then line=1; else line=2; fi
expected="$(sed -n 's/^ *sha256 "\([0-9a-f]\{64\}\)".*/\1/p' "$work/agenticos.rb" | sed -n "${line}p")"
actual="$(shasum -a 256 "$work/$dmg" | cut -d ' ' -f 1)"
if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
  echo "Checksum mismatch for $dmg: expected '$expected', got '$actual'. Nothing was installed." >&2
  exit 1
fi
echo "Checksum verified."

mount="$(hdiutil attach "$work/$dmg" -nobrowse -readonly | sed -n 's|.*\(/Volumes/.*\)$|\1|p' | tail -n 1)"
[ -d "$mount/AgenticOS.app" ] || { echo "AgenticOS.app is not in the disk image." >&2; exit 1; }

if [ -d "$dest/AgenticOS.app" ] && pgrep -x agenticos-desktop >/dev/null; then
  echo "Quit AgenticOS first, then run this again." >&2
  exit 1
fi
# A checksum published beside the download proves the download is the one that was
# published, not who published it. Where the project has pinned the certificate its
# releases are signed with, the app must carry that signature or nothing is installed.
pinned="$(curl -fsSL "$pin_url" 2>/dev/null | grep -E '^[0-9a-fA-F]{40}$' | head -n 1 | tr 'A-F' 'a-f' || true)"
if [ -n "$pinned" ]; then
  codesign --verify --deep --strict "$mount/AgenticOS.app" \
    || { echo "The app's signature does not verify. Nothing was installed." >&2; exit 1; }
  if ! codesign -d -r- "$mount/AgenticOS.app" 2>&1 | grep -q "certificate root = H\"$pinned\""; then
    echo "The app was not signed by the certificate this project pins. Nothing was installed." >&2
    exit 1
  fi
  echo "Signature verified against the pinned publisher certificate."
else
  echo "Note: no publisher certificate is pinned yet, so only the checksum published with" >&2
  echo "the release was checked - it proves the download is that release, not who made it." >&2
fi

mkdir -p "$dest"
rm -rf "$dest/AgenticOS.app"
ditto "$mount/AgenticOS.app" "$dest/AgenticOS.app"
xattr -dr com.apple.quarantine "$dest/AgenticOS.app"
echo "Installed $dest/AgenticOS.app. Open it from Launchpad or Spotlight."
