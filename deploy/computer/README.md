# computerd

The desktop that the `computer_use` capability drives when its `backend` is
`daemon`. `computerd.py` is a single file. It takes screenshots and carries out
mouse and keyboard actions behind a bearer token. The capability's own README is
at `backend/app/agents/capabilities/computer_use/README.md`, and the
operator-facing page is `docs/reference/capabilities.md#computer-use`.

One daemon is one desktop. Every run pointed at it shares the machine and
whatever is signed in there, so give it a machine or an account of its own.

## A Linux desktop in a container

```bash
docker build -t agenticos-computer deploy/computer
docker run -d --name agenticos-computer --shm-size=1g \
  -e COMPUTERD_TOKEN="$COMPUTER_DAEMON_TOKEN" \
  -p 127.0.0.1:8765:8765 agenticos-computer
```

The image runs Xvfb, XFCE and Firefox as an unprivileged user (`desk`, uid
10001). `SCREEN_SIZE` defaults to `1280x800`. Set `VNC_PASSWORD` and publish
port 6080 to watch the whole session in noVNC; without it, no VNC server starts,
because VNC means full control of the desktop.

## A Mac's own screen

```bash
COMPUTERD_TOKEN="$COMPUTER_DAEMON_TOKEN" uv run deploy/computer/computerd.py
```

The inline script metadata pulls in Quartz. The first time it runs, macOS asks
for Screen Recording and Accessibility for the app that started it (the
terminal). Until both are granted, screenshots fail or show only the wallpaper,
and clicks do nothing. The daemon listens on `127.0.0.1` unless `COMPUTERD_HOST`
says otherwise. A deployment running in Docker on the same Mac reaches it at
`host.docker.internal`.

## Your own Linux desktop

```bash
COMPUTERD_TOKEN="$COMPUTER_DAEMON_TOKEN" python3 deploy/computer/computerd.py
```

On X11 it needs `scrot` and `xdotool`. In a KDE Plasma session on Wayland, which
it picks when `WAYLAND_DISPLAY` is set, those reach only XWayland windows, so it
uses `spectacle` for screenshots and `dotool` for input instead. `dotool` writes
to `/dev/uinput`, so the user running it needs write access there (on NixOS,
`hardware.uinput.enable` and the `uinput` group), and `DOTOOL_XKB_LAYOUT` set to
the keyboard layout for typed text to come out right. Other Wayland desktops are
not supported.

## Pointing a deployment at it

| Where | Setting |
|---|---|
| The daemon | `COMPUTERD_TOKEN`, at least 16 characters |
| The deployment | `COMPUTER_DAEMON_TOKEN`, the same value |
| The deployment | `COMPUTER_DAEMON_ALLOWED_HOSTS`, the daemon's hostname |
| The agent's spec | `daemon_url`, e.g. `http://host.docker.internal:8765` |

Publish refuses a `daemon_url` whose host is not on the allowlist. The port is
not encrypted, so keep it on loopback or a private network. To reach a remote
machine, use an SSH tunnel (`ssh -N -L 8766:127.0.0.1:8765 host`) rather than
binding to `0.0.0.0`.
