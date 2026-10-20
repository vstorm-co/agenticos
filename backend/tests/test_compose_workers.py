"""Every multi-worker uvicorn gives its workers a ping window a starved host can meet.

Uvicorn's supervisor pings each worker over a pipe and kills one that has not
answered within `--timeout-worker-healthcheck`, 5 seconds unless told otherwise.
On a host short of CPU that killed live workers and their half-started
replacements 17 times in 20 minutes (#2223). A blocked event loop is the
watchdog's to judge (`app/core/watchdog.py`), so the ping only has to catch a
stopped process and can wait a minute.

Walks every compose file rather than naming services, because the next file to
run uvicorn with `--workers` is the one nobody would think to add here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose-prod.yml",
    "deploy/profiles/ml-services/docker-compose.ml.yml",
)
FLAG = "--timeout-worker-healthcheck"
# Long enough for a starved host to answer; the watchdog covers anything shorter.
MINIMUM_SECONDS = 30


class _ComposeLoader(yaml.SafeLoader):
    """Reads Compose's own merge tags (`!reset`, `!override`) as plain values."""


def _untagged(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> object:
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    assert isinstance(node, yaml.ScalarNode)
    return loader.construct_scalar(node)


_ComposeLoader.add_multi_constructor("!", _untagged)


def _uvicorn_commands(file_name: str) -> list[tuple[str, str]]:
    with (REPO_ROOT / file_name).open() as handle:
        loaded: dict[str, Any] = yaml.load(handle, Loader=_ComposeLoader)  # noqa: S506 - a SafeLoader subclass
    commands: list[tuple[str, str]] = []
    for name, service in loaded["services"].items():
        command = service.get("command")
        if isinstance(command, list):
            command = " ".join(str(part) for part in command)
        if isinstance(command, str) and command.startswith("uvicorn"):
            commands.append((name, command))
    return commands


def _default(command: str, flag: str) -> int:
    """The number a flag is given, reading a `${VAR:-N}` default where it is one."""
    match = re.search(rf"{flag} (?:\$\{{\w+:-(\d+)\}}|(\d+))", command)
    assert match is not None, f"{flag} has no value in: {command}"
    return int(match.group(1) or match.group(2))


@pytest.mark.parametrize("file_name", COMPOSE_FILES)
def test_every_multi_worker_uvicorn_sets_a_long_ping_window(file_name: str) -> None:
    commands = [
        (name, command) for name, command in _uvicorn_commands(file_name) if "--workers" in command
    ]
    assert commands, (
        f"{file_name}: no uvicorn command with --workers - the parametrization is stale"
    )
    for name, command in commands:
        assert FLAG in command, f"{file_name}: {name} runs --workers without {FLAG}"
        assert _default(command, FLAG) >= MINIMUM_SECONDS, (
            f"{file_name}: {name} gives its workers under {MINIMUM_SECONDS}s to answer the ping"
        )


def test_the_default_reads_a_variable_with_a_number_or_a_literal() -> None:
    """Guards the parser the test above relies on."""
    assert _default(f"uvicorn x {FLAG} ${{SOME_VAR:-60}} --ws y", FLAG) == 60
    assert _default(f"uvicorn x {FLAG} 45", FLAG) == 45
