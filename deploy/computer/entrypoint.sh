#!/bin/sh
# Start the display, the desktop on it, an optional VNC view, then computerd.
set -eu

# A restarted container keeps its /tmp, and Xvfb refuses a display whose lock
# survived the last one. Nothing else in this container serves the display.
rm -f "/tmp/.X${DISPLAY#:}-lock" "/tmp/.X11-unix/X${DISPLAY#:}"

Xvfb "$DISPLAY" -screen 0 "${SCREEN_SIZE}x24" -nolisten tcp &
for _ in $(seq 50); do
    xdpyinfo >/dev/null 2>&1 && break || sleep 0.1
done
# Without a display every screenshot fails while /health still answers, so the
# container exits and its restart policy tries again.
if ! xdpyinfo >/dev/null 2>&1; then
    echo "computerd: Xvfb did not start on $DISPLAY" >&2
    exit 1
fi

dbus-launch --exit-with-session startxfce4 >/tmp/xfce.log 2>&1 &

# A person watching the whole session, not only the frames the agent takes. Off
# unless VNC_PASSWORD is set: a VNC server is full control of the desktop.
if [ -n "${VNC_PASSWORD:-}" ]; then
    x11vnc -display "$DISPLAY" -forever -shared -quiet -passwd "$VNC_PASSWORD" -rfbport 5900 >/tmp/x11vnc.log 2>&1 &
    websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/novnc.log 2>&1 &
fi

exec python3 /opt/computerd/computerd.py
