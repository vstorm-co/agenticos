"""The default deployment check prepares a plan without running Docker."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_default_smoke_check_does_not_need_a_container_engine() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/agenticos_smoke.py"), "--version", "1.84.0"],
        env={**os.environ, "PATH": ""},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "Plan: disposable Compose project" in result.stdout
    assert "Add --run to execute" in result.stdout
