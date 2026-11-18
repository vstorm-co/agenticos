#!/usr/bin/env bash
set -euo pipefail

test "$(id -u)" != 0
BACKEND="${1:?Expected x11 or wayland}"
OUTPUT="${OUTPUT:?Expected diagnostic output directory}"
export XDG_RUNTIME_DIR
XDG_RUNTIME_DIR="$(mktemp -d)"
export XDG_CONFIG_HOME="$XDG_RUNTIME_DIR/config" XDG_DATA_HOME="$XDG_RUNTIME_DIR/data"
export XDG_CACHE_HOME="$XDG_RUNTIME_DIR/cache" LIBGL_ALWAYS_SOFTWARE=1
trap 'rm -rf "$XDG_RUNTIME_DIR"' EXIT
case "$BACKEND" in
  x11)
    timeout 120 dbus-run-session -- xvfb-run -a env GDK_BACKEND=x11 agenticos --installation-smoke
    ;;
  wayland)
    weston --backend=headless --renderer=pixman --socket=agenticos-smoke --idle-time=0 > "$OUTPUT/weston.log" 2>&1 &
    WESTON_PID=$!
    trap 'kill "$WESTON_PID" 2>/dev/null || true; wait "$WESTON_PID" 2>/dev/null || true; rm -rf "$XDG_RUNTIME_DIR"' EXIT
    for ((ATTEMPT = 0; ATTEMPT < 100; ATTEMPT++)); do
      test ! -S "$XDG_RUNTIME_DIR/agenticos-smoke" || break
      kill -0 "$WESTON_PID"
      sleep 0.1
    done
    test -S "$XDG_RUNTIME_DIR/agenticos-smoke"
    timeout 120 dbus-run-session -- env GDK_BACKEND=wayland WAYLAND_DISPLAY=agenticos-smoke agenticos --installation-smoke
    ;;
  *) exit 2 ;;
esac
