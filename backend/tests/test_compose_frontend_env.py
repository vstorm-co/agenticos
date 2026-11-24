"""What every compose file hands the console's container from the operator's `.env`."""

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _consoles() -> list[tuple[str, list[str]]]:
    """Each compose file that defines the console's environment, with that environment."""
    found = []
    for path in sorted(REPO_ROOT.glob("docker-compose*.yml")):
        loaded: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
        environment = (loaded.get("services") or {}).get("frontend", {}).get("environment")
        if environment:
            found.append((path.name, list(environment)))
    return found


def test_the_compose_files_define_a_console() -> None:
    assert {name for name, _ in _consoles()} >= {
        "docker-compose.yml",
        "docker-compose-prod.frontend.yml",
        "docker-compose-dev.frontend.yml",
    }


@pytest.mark.parametrize(("name", "environment"), _consoles())
def test_the_session_cookie_namespace_reaches_the_console(
    name: str, environment: list[str]
) -> None:
    """Two deployments on one host name share cookies across ports, so signing in to
    one signs out of the other unless each console names its cookies apart."""
    assert "SESSION_COOKIE_NAMESPACE=${SESSION_COOKIE_NAMESPACE:-}" in environment, name
