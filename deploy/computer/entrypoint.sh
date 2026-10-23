#!/bin/sh
# Start the display, the desktop on it, an optional VNC view, then computerd.
#
# Run as root, only to split the work between two accounts. The desktop the
# agent drives runs as `desk`; it has a terminal, so whatever `desk` can read the
# agent can put on screen. The daemon's token and the VNC password therefore
# stay with `computerd`, whose processes and files `desk` cannot read.
set -eu

# Only ever started with `&`, so `exec` replaces the subshell `&` made rather
# than this script, and no root process is left waiting behind each one.
as_desk() {
    exec setpriv --reuid=desk --regid=desk --init-groups --reset-env \
        env DISPLAY="$DISPLAY" LANG="$LANG" "$@"
}

as_daemon() {
    exec setpriv --reuid=computerd --regid=computerd --init-groups "$@"
}

# Kept as unexported shell variables from here on: nothing started below
# inherits them, and none of them appears on a command line, which `ps` shows
# to every account.
token="${COMPUTERD_TOKEN:-}"
vnc_password="${VNC_PASSWORD:-}"
unset COMPUTERD_TOKEN VNC_PASSWORD

# A restarted container keeps its /tmp, and Xvfb refuses a display whose lock
# survived the last one. Nothing else in this container serves the display.
rm -f "/tmp/.X${DISPLAY#:}-lock" "/tmp/.X11-unix/X${DISPLAY#:}"

as_desk Xvfb "$DISPLAY" -screen 0 "${SCREEN_SIZE}x24" -nolisten tcp &
for _ in $(seq 50); do
    xdpyinfo >/dev/null 2>&1 && break || sleep 0.1
done
# Without a display every screenshot fails while /health still answers, so the
# container exits and its restart policy tries again.
if ! xdpyinfo >/dev/null 2>&1; then
    echo "computerd: Xvfb did not start on $DISPLAY" >&2
    exit 1
fi

as_desk dbus-launch --exit-with-session startxfce4 >/tmp/xfce.log 2>&1 &

# A person watching the whole session, not only the frames the agent takes. Off
# unless VNC_PASSWORD is set: a VNC server is full control of the desktop.
if [ -n "$vnc_password" ]; then
    install -d -m 0700 -o computerd -g computerd /run/computerd
    (umask 077 && printf '%s\n' "$vnc_password" >/run/computerd/vnc-password)
    chown computerd:computerd /run/computerd/vnc-password
    # `-noshm`: the X server runs as `desk` and may not attach memory another
    # account made, which is the point of the split.
    as_daemon x11vnc -display "$DISPLAY" -forever -shared -quiet -noshm \
        -passwdfile /run/computerd/vnc-password -rfbport 5900 >/tmp/x11vnc.log 2>&1 &
    as_daemon websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/novnc.log 2>&1 &
fi

export COMPUTERD_TOKEN="$token"
exec setpriv --reuid=computerd --regid=computerd --init-groups python3 /opt/computerd/computerd.py
