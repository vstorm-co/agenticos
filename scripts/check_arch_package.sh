#!/usr/bin/env bash
set -euo pipefail

# This mutates package state and runs GUI processes only inside the disposable CI container.
test "${CI:-}" = true
test "$(id -u)" = 0
OUTPUT="$(realpath "${1:?Usage: check_arch_package.sh BUILD_DIRECTORY}")"
PACKAGE="$(find "$OUTPUT" -maxdepth 1 -name 'agenticos-*-1-x86_64.pkg.tar.zst' -print)"
test -f "$PACKAGE"
pacman -U --noconfirm "$PACKAGE"
trap 'pacman -R --noconfirm agenticos' EXIT
pacman -Q agenticos
pacman -Qk agenticos
ldd /usr/bin/agenticos | tee "$OUTPUT/linked-libraries.txt"
if grep -q 'not found' "$OUTPUT/linked-libraries.txt"; then
  exit 1
fi
grep -q '/usr/lib/libwebkit2gtk-4.1.so' "$OUTPUT/linked-libraries.txt"
desktop-file-validate /usr/share/applications/co.vstorm.agenticos.desktop

# The independently built next package revision exercises upgrade ownership.
UPGRADE="$(find "$OUTPUT" -maxdepth 1 -name 'agenticos-*-2-x86_64.pkg.tar.zst' -print)"
pacman -U --noconfirm "$UPGRADE"
[[ "$(pacman -Q agenticos)" = *-2 ]]
pacman -Qk agenticos

pacman -Q webkit2gtk-4.1 gtk3 mesa weston xorg-server-xvfb > "$OUTPUT/tested-environment.txt"
uname -a >> "$OUTPUT/tested-environment.txt"
for BACKEND in x11 wayland; do
  runuser -u builder -- env OUTPUT="$OUTPUT" bash "$(dirname "$0")/arch_render_smoke.sh" "$BACKEND" 2>&1 | tee "$OUTPUT/render-$BACKEND.log"
done
pacman -R --noconfirm agenticos
trap - EXIT
if pacman -Q agenticos; then
  exit 1
fi
test ! -e /usr/bin/agenticos
test ! -e /usr/share/applications/co.vstorm.agenticos.desktop
test ! -e /usr/share/icons/hicolor/128x128/apps/co.vstorm.agenticos.png
