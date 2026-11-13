"""The development workspace setup checks the service's effective mode class."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAKE = shutil.which("make")
assert MAKE is not None


@pytest.mark.parametrize(
    ("owner", "group", "mode", "warns"),
    [
        (10001, 10001, 0o555, True),
        (10001, 10001, 0o700, False),
        (10001, 10001, 0o003, True),
        (12345, 999, 0o030, False),
        (12345, 10001, 0o030, True),
        (12345, 12345, 0o003, False),
        (12345, 12345, 0o002, True),
    ],
)
def test_existing_workspace_requires_write_and_search(
    tmp_path: Path, owner: int, group: int, mode: int, warns: bool
) -> None:
    directory = tmp_path / "workspace"
    directory.mkdir()
    directory.chmod(mode)
    commands = tmp_path / "bin"
    commands.mkdir()
    # Simulate the container's numeric owner without requiring root on the host.
    ls = commands / "ls"
    ls.write_text(
        f"#!/bin/sh\necho '{stat.filemode(stat.S_IFDIR | mode)} 1 {owner} {group} 0 workspace'\n"
    )
    ls.chmod(0o755)
    try:
        result = subprocess.run(
            [
                MAKE,
                "--no-print-directory",
                "sandbox-workspace",
                f"SANDBOX_WORKSPACE_ROOT={directory}",
            ],
            cwd=ROOT,
            env={**os.environ, "PATH": f"{commands}:{os.environ['PATH']}"},
            text=True,
            capture_output=True,
            check=True,
        )
        assert ("needs write and search access" in result.stdout) is warns
    finally:
        directory.chmod(0o700)


def test_missing_workspace_is_created_with_the_sticky_bit(tmp_path: Path) -> None:
    directory = tmp_path / "workspace"
    subprocess.run(
        [MAKE, "--no-print-directory", "sandbox-workspace", f"SANDBOX_WORKSPACE_ROOT={directory}"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    assert directory.stat().st_mode & 0o7777 == 0o1777
