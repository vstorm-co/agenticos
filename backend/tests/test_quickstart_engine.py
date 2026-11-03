"""Exercise quickstart prerequisites without starting or modifying a stack."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "cli,server,compose,has_docker,has_podman,expected",
    [
        (
            "docker version 6.1.4",
            "",
            "2.40.3",
            True,
            True,
            "Podman deployments use the manual setup",
        ),
        (
            "podman version 5.6.2",
            "",
            "1.6.0",
            True,
            True,
            "Podman deployments use the manual setup",
        ),
        (
            "podman version 5.6.2",
            "",
            "2.30.0",
            True,
            True,
            "Podman deployments use the manual setup",
        ),
        (
            "Docker version 28.0.0",
            "Podman Engine",
            "2.30.0",
            True,
            False,
            "Podman deployments use the manual setup",
        ),
        (
            "Docker version 28.0.0",
            "Docker Engine - Community",
            "podman-compose version 1.6.0",
            True,
            True,
            "Podman deployments use the manual setup",
        ),
        ("", "", "", False, True, "Podman deployments use the manual setup"),
        (
            "Docker version 28.0.0",
            "Engine\ncontainerd\nrunc\ndocker-init",
            "2.24.0",
            True,
            True,
            "Everything",
        ),
        ("Docker version 28.0.0", "Docker Desktop", "v2.30.0", True, False, "Everything"),
        ("Docker version 28.0.0", "Docker Engine - Community", "2.23.0", True, False, "is too old"),
        ("Docker version 28.0.0", "", "2.30.0", True, False, "Docker is installed but not running"),
        ("", "", "", False, False, "docker is missing"),
    ],
)
@pytest.mark.parametrize("sandbox_flag", ["--sandbox", "--no-sandbox"])
def test_quickstart_reports_the_engine_before_compose_compatibility(
    tmp_path: Path,
    cli: str,
    server: str,
    compose: str,
    has_docker: bool,
    has_podman: bool,
    expected: str,
    sandbox_flag: str,
) -> None:
    commands = tmp_path / "bin"
    commands.mkdir()
    for name in ("uname", "grep"):
        binary = shutil.which(name)
        assert binary is not None
        (commands / name).symlink_to(binary)
    for name in ("curl", "podman") if has_podman else ("curl",):
        command = commands / name
        command.write_text("#!/bin/sh\nexit 0\n")
        command.chmod(0o755)
    if has_docker:
        command = commands / "docker"
        command.write_text(
            "#!/bin/sh\n"
            'printf "%s\\n" "$*" >> "$CALLS"\n'
            'case "$*" in\n'
            '  --version) printf "%s\\n" "$CLI" ;;\n'
            '  "system connection list --format "*) case "$CLI" in "docker version "*) exit 0 ;; *) exit 1 ;; esac ;;\n'
            '  "version --format "*".Server.Components"*) printf "%s\\n" "$SERVER" ;;\n'
            '  "version --format "*) printf "%s\\n" "linux/arm64/fedora-44" ;;\n'
            '  "compose version"*) printf "%s\\n" "$COMPOSE" ;;\n'
            '  info) [ -n "$SERVER" ] ;;\n'
            "  *) exit 99 ;;\n"
            "esac\n"
        )
        command.chmod(0o755)
    calls = tmp_path / "calls"
    result = subprocess.run(
        [
            shutil.which("bash") or "/bin/bash",
            str(ROOT / "scripts/quickstart.sh"),
            "--check",
            sandbox_flag,
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(commands),
            "CLI": cli,
            "SERVER": server,
            "COMPOSE": compose,
            "CALLS": str(calls),
            "NO_COLOR": "1",
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    output = result.stdout + result.stderr
    assert expected in output
    assert result.returncode == (0 if expected == "Everything" else 1)
    if expected == "Podman deployments use the manual setup":
        assert "Docker Engine with Docker Compose 2.24+" in output
        assert "deploy/#podman-support" in output
        assert "is too old" not in output
    if "podman" in cli or cli.startswith("docker version ") or server == "Podman Engine":
        assert "compose" not in calls.read_text()
    assert not (tmp_path / "agenticos").exists()
    assert not (tmp_path / ".env").exists()
