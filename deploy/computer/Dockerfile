# A Linux desktop for AgenticOS's `computer_use` capability: Xvfb, XFCE, Firefox,
# and computerd on :8765. See README.md.
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        xvfb x11-utils xfce4 xfce4-terminal dbus-x11 xdotool scrot python3 \
        firefox-esr fonts-dejavu-core fonts-noto-color-emoji ca-certificates \
        x11vnc novnc websockify procps \
    && rm -rf /var/lib/apt/lists/*

# Two accounts: `desk` is the desktop the agent drives, and `computerd` holds the
# token. The entrypoint starts as root to split them - see entrypoint.sh.
RUN useradd --create-home --uid 10001 --shell /bin/bash desk \
    && useradd --system --uid 10002 --no-create-home --shell /usr/sbin/nologin computerd
COPY --chmod=0755 computerd.py /opt/computerd/computerd.py
COPY --chmod=0755 entrypoint.sh /opt/computerd/entrypoint.sh

WORKDIR /home/desk
# Without a UTF-8 locale the desktop's apps drop every non-ASCII character typed into them.
ENV DISPLAY=:0 \
    LANG=C.UTF-8 \
    SCREEN_SIZE=1280x800 \
    COMPUTERD_HOST=0.0.0.0 \
    COMPUTERD_PORT=8765

EXPOSE 8765 6080
HEALTHCHECK --interval=15s --timeout=3s CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health')"
ENTRYPOINT ["/opt/computerd/entrypoint.sh"]
