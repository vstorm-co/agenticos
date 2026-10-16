#!/bin/sh
# A virtual display, Chromium on it, and DevTools reachable from the network.
#
# Chromium binds DevTools to loopback when it has a window (the address flag is
# honoured only by a headless browser), so socat forwards 9222 on every interface
# to it. `browser_use` speaks to it by address, which is what Chromium's Host
# check accepts.
set -eu

Xvfb :99 -screen 0 "$SCREEN" -nolisten tcp -ac >/dev/null 2>&1 &
export DISPLAY=:99
# No session bus in a container; without this Chromium logs a failed connection
# to one on every start.
export DBUS_SESSION_BUS_ADDRESS=disabled:

socat TCP-LISTEN:9222,fork,reuseaddr,bind=0.0.0.0 TCP:127.0.0.1:9223 &

# --no-sandbox: the container is the sandbox, and Chromium's own needs privileges
# a container does not grant. No --enable-automation and no --headless: those are
# what a page reads as "driven". WebGL is drawn in software (SwiftShader), because
# a browser with no WebGL context at all is the one desktop never has.
exec chromium \
    --remote-debugging-port=9223 \
    --remote-debugging-address=127.0.0.1 \
    --user-data-dir=/home/chrome/profile \
    --no-sandbox \
    --no-first-run \
    --no-default-browser-check \
    --disable-blink-features=AutomationControlled \
    --use-gl=angle \
    --use-angle=swiftshader \
    --enable-unsafe-swiftshader \
    --ignore-gpu-blocklist \
    --disable-features=Translate,MediaRouter,OptimizationHints \
    --password-store=basic \
    --use-mock-keychain \
    --lang="$BROWSER_LANG" \
    --window-position=0,0 \
    --window-size="$(echo "$SCREEN" | cut -dx -f1),$(echo "$SCREEN" | cut -dx -f2)" \
    --start-maximized \
    about:blank
