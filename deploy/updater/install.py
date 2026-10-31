"""Install the optional host updater once on a Linux/systemd Compose server.

Run explicitly as root from a reviewed AgenticOS checkout. This installs a service
but does not deploy, migrate, restart or update the AgenticOS application itself.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def install(*, app_dir: Path, backend_project: str, api_gid: int) -> None:
    if os.geteuid() != 0 or shutil.which("systemctl") is None:
        raise SystemExit("Run as root on a Linux server with systemd; see deploy/updater/README.md")
    app_dir = app_dir.resolve(strict=True)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", backend_project):
        raise SystemExit("Invalid Compose project name")
    if (
        not (app_dir / "backend/.env").is_file()
        or not (app_dir / "docker-compose-prod.updater.yml").is_file()
    ):
        raise SystemExit("A configured AgenticOS production checkout is required")
    # Paths enter a systemd unit and the operator's environment file, so reject
    # whitespace and quoting rather than pretending shell escaping applies there.
    if not re.fullmatch(r"/[a-zA-Z0-9_./-]+", str(app_dir)):
        raise SystemExit("Use an application path without spaces or shell metacharacters")
    program = Path("/opt/agenticos-updater")
    state, runtime = Path("/var/lib/agenticos-updater"), Path("/run/agenticos-updater")
    for directory in (program, state):
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
    runtime.mkdir(mode=0o750, exist_ok=True)
    os.chown(runtime, 0, api_gid)
    runtime.chmod(0o750)
    shutil.copy2(Path(__file__).with_name("agent.py"), program / "agent.py")
    config = {
        "app_dir": str(app_dir),
        "state_dir": str(state),
        "runtime_dir": str(runtime),
        "backend_project": backend_project,
        "api_gid": api_gid,
    }
    (program / "config.json").write_text(json.dumps(config))
    (program / "config.json").chmod(0o600)
    (Path("/etc/systemd/system") / "agenticos-updater.service").write_text(
        "[Unit]\nDescription=AgenticOS local Compose updater\nAfter=docker.service\nRequires=docker.service\n"
        "[Service]\nType=simple\nUser=root\nUMask=0077\nRuntimeDirectory=agenticos-updater\nRuntimeDirectoryMode=0750\n"
        "ExecStart=/usr/bin/python3 /opt/agenticos-updater/agent.py --config /opt/agenticos-updater/config.json\n"
        "Restart=on-failure\nRestartSec=5\nTimeoutStopSec=1500\nNoNewPrivileges=true\nPrivateTmp=true\n"
        "[Install]\nWantedBy=multi-user.target\n"
    )
    subprocess.run(["/usr/bin/systemctl", "daemon-reload"], check=True)
    subprocess.run(
        ["/usr/bin/systemctl", "enable", "--now", "agenticos-updater.service"], check=True
    )
    sys.stdout.write(
        "Updater installed. To connect the API and worker, add the updater overlay on their next intentional restart:\n"
    )
    sys.stdout.write(
        f"UPDATE_STATE_DIR={runtime} docker compose --env-file backend/.env -p {backend_project} -f docker-compose-prod.yml -f docker-compose-prod.updater.yml up -d\n"
    )
    sys.stdout.write(
        "Keep any existing proxy overlays and Compose profiles. No application update was performed.\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, required=True)
    parser.add_argument("--backend-project", required=True)
    parser.add_argument("--api-gid", type=int, default=1000)
    args = parser.parse_args()
    install(app_dir=args.app_dir, backend_project=args.backend_project, api_gid=args.api_gid)
