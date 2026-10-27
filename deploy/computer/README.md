# computerd

The desktop that the `computer_use` capability drives when its `backend` is
`daemon`. `computerd.py` is a single file. It takes screenshots and carries out
mouse and keyboard actions behind a bearer token. The capability's own README is
at `backend/app/agents/capabilities/computer_use/README.md`, and the
operator-facing page is `docs/reference/capabilities.md#computer-use`.

One daemon is one desktop. Every run pointed at it shares the machine and
whatever is signed in there, so give it a machine or an account of its own.
The agent can read anything the account running the daemon can, its token
included, unless the daemon runs as another account, as it does in the
container.

## A Linux desktop in a container

```bash
docker build -t agenticos-computer deploy/computer
docker run -d --name agenticos-computer --shm-size=1g \
  -e COMPUTERD_TOKEN="$(openssl rand -hex 24)" \
  -p 127.0.0.1:8765:8765 agenticos-computer
```

The desktop - Xvfb, XFCE and Firefox - runs as `desk` (uid 10001), and
computerd and the VNC server as `computerd` (uid 10002). The agent drives the
desktop and the desktop has a terminal, so anything `desk` can read the agent
can show on screen. `desk` cannot read the token, the VNC password or either
process's environment. The container therefore starts as root, only to start
each process as its account; do not run it with `--user`, and keep `SETUID` and
`SETGID` if you drop capabilities. An application a `launch` action opens is
started by a launcher running as `desk`, which computerd asks over a socket in
`/run/launcher` that only the two accounts can reach, so the application never
runs as the account holding the token. It starts each application in a session
of its own, and quits it by ending that session when the run that launched it
ends. `SCREEN_SIZE` defaults to `1280x800`. Set
`VNC_PASSWORD` and publish port 6080 to watch the whole session in noVNC;
without it, no VNC server starts, because VNC means full control of the
desktop.

## A Mac's own screen

```bash
COMPUTERD_TOKEN="<the token>" uv run deploy/computer/computerd.py
```

The inline script metadata pulls in Quartz. The first time it runs, macOS asks
for Screen Recording and Accessibility for the app that started it (the
terminal). Until both are granted, screenshots fail or show only the wallpaper,
and clicks do nothing. A `launch` action runs `open -a` with the application's
name, and the end of the run quits it with `quit saving no` unless it was
running already. The daemon listens on `127.0.0.1` unless `COMPUTERD_HOST`
says otherwise. A deployment running in Docker on the same Mac reaches it at
`host.docker.internal`.

## Pointing a deployment at it

| Where | Setting |
|---|---|
| The daemon | `COMPUTERD_TOKEN`, at least 16 characters |
| The organization's vault | An API key holding the same value, named on the capability |
| The deployment | `COMPUTER_DAEMON_ALLOWED_HOSTS`, the daemon's hostname |
| The agent's spec | `daemon_url`, e.g. `http://host.docker.internal:8765` |

Publish refuses a `daemon_url` whose host is not on the allowlist, and a run
refuses it again if the host has been removed since. The token belongs to the
organization whose agents drive the desktop: every organization can name an
allowed host, so a desktop's token is what keeps the others out. Give each
desktop its own. The port is
not encrypted, so keep it on loopback or a private network. To reach a remote
machine, use an SSH tunnel (`ssh -N -L 8766:127.0.0.1:8765 host`) rather than
binding to `0.0.0.0`.
