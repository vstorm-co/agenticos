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

RUN useradd --create-home --uid 10001 --shell /bin/bash desk
COPY --chmod=0755 computerd.py /opt/computerd/computerd.py
COPY --chmod=0755 entrypoint.sh /opt/computerd/entrypoint.sh

USER desk
WORKDIR /home/desk
ENV DISPLAY=:0 \
    SCREEN_SIZE=1280x800 \
    COMPUTERD_HOST=0.0.0.0 \
    COMPUTERD_PORT=8765

EXPOSE 8765 6080
HEALTHCHECK --interval=15s --timeout=3s CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health')"
ENTRYPOINT ["/opt/computerd/entrypoint.sh"]
