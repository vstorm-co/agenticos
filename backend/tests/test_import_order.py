import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "module",
    [
        "app.main",
        "app.services.artifact",
        "app.services.artifact_bindings",
        "app.services.virtual_tables",
        "app.services.agent_runner",
        "app.services.workflow_execution",
        "app.agents.capabilities.virtual_tables",
        "app.agents.capabilities.artifacts",
        "app.agents.factory",
        "app.agents.audience",
        "app.agents.deps",
    ],
)
def test_each_entry_module_imports_first_in_a_fresh_interpreter(module: str) -> None:
    """A cold interpreter per module: a cycle only shows for the module imported first.

    `python -c` puts the working directory first on `sys.path`, so `import app`
    resolves from `backend/`.
    """
    loaded = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )

    assert loaded.returncode == 0, f"importing {module} first failed:\n{loaded.stderr}"
