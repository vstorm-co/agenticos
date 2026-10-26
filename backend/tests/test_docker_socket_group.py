"""Run the actual launch snippets against each host's socket ownership."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("platform,gid", [("Darwin", "0"), ("Linux", "998")])
@pytest.mark.parametrize("override", [None, "42"])
@pytest.mark.parametrize("entrypoint", ["Makefile", "scripts/deploy.sh", "scripts/quickstart.sh"])
def test_launchers_use_the_container_socket_group(
    tmp_path: Path, platform: str, gid: str, override: str | None, entrypoint: str
) -> None:
    for name, body in {
        "uname": f"echo {platform}",
        "stat": (
            'case " $* " in *" -L"*|*" --dereference"*) echo 998 ;; *) echo 1 ;; esac'
            if platform == "Linux"
            else "echo 1"
        ),
    }.items():
        command = tmp_path / name
        command.write_text(f"#!/bin/sh\n{body}\n")
        command.chmod(0o755)
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DOCKER_GID", "MAKEFLAGS", "MAKELEVEL", "MAKEOVERRIDES", "MFLAGS"}
    }
    env["PATH"] = f"{tmp_path}:{os.environ['PATH']}"
    if override is not None:
        env["DOCKER_GID"] = override
    source = (ROOT / entrypoint).read_text()
    if entrypoint == "Makefile":
        snippet = source.split("# The sandbox service refuses", 1)[0]
        probe = tmp_path / "probe.mk"
        probe.write_text(snippet + '\nprobe:\n\t@echo "$$DOCKER_GID"\n')
        args = ["make", "--no-print-directory", "-f", str(probe), "probe"]
    else:
        # These scripts execute immediately, so exercise only the group detection.
        start = source.index('  if [ -z "${DOCKER_GID+x}" ]; then')
        end = source.index("  export DOCKER_GID", start) + len("  export DOCKER_GID")
        args = ["bash", "-eu", "-c", source[start:end] + '\necho "$DOCKER_GID"']
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10, check=True)
    assert result.stdout.strip() == (override if override is not None else gid)
