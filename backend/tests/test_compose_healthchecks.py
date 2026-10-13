"""A dependency nothing can start without owes its health status a grace.

`depends_on: condition: service_healthy` reads the dependency's health status the
instant the container starts. Two things can be true at that moment and neither
is a verdict on this run: the service has not finished starting, and - on a
daemon that carried it across the restart - the status is the one the previous
run left behind. Both read as `unhealthy`, compose gives up on the spot, and the
deploy fails half a second after starting the very container that repaired it
(#1831).

`start_period` is what `service_healthy` is meant to wait through, and every
healthcheck something waits on had better declare one. This walks the compose
files rather than naming services, because the next dependency added with a
`service_healthy` gate is the one nobody would think to add a test for.

The half a compose file cannot state - a status the daemon keeps across a
restart - is `scripts/deploy.sh`'s. Its two functions are run here against a
stubbed `docker` and `compose`, because the shape of that bug is a control flow
nobody can read off the script with confidence: one retry for this failure and
no other, and an `unhealthy` acted on only once a probe has run since the
container started.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy.sh"

# Every compose file that runs a stack with dependencies between its services.
# The frontend files are one service each and wait on nothing.
COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose-dev.yml",
    "docker-compose-prod.yml",
)


def _services(file_name: str) -> dict[str, Any]:
    with (REPO_ROOT / file_name).open() as handle:
        loaded: dict[str, Any] = yaml.safe_load(handle)
    services: dict[str, Any] = loaded["services"]
    return services


def _awaited_healthy(services: dict[str, Any]) -> set[str]:
    """The services some other service refuses to start without."""
    awaited: set[str] = set()
    for service in services.values():
        depends_on = service.get("depends_on") or {}
        for name, spec in depends_on.items():
            if isinstance(spec, dict) and spec.get("condition") == "service_healthy":
                awaited.add(name)
    return awaited


@pytest.mark.parametrize("file_name", COMPOSE_FILES)
class TestEveryAwaitedHealthcheckHasAGrace:
    def test_something_in_this_file_waits_on_a_healthy_service(self, file_name: str) -> None:
        """Guards the parametrization itself: an empty set would pass everything."""
        assert _awaited_healthy(_services(file_name))

    def test_each_one_declares_a_start_period(self, file_name: str) -> None:
        services = _services(file_name)
        for name in sorted(_awaited_healthy(services)):
            healthcheck = services[name].get("healthcheck")
            assert healthcheck is not None, f"{file_name}: {name} has no healthcheck"
            assert "start_period" in healthcheck, (
                f"{file_name}: {name} is waited on with condition: service_healthy "
                "and declares no start_period"
            )


def _function(name: str) -> str:
    """One function verbatim out of `deploy.sh`.

    The script cannot be sourced: it deploys a commit as soon as it is read.
    """
    lines = DEPLOY_SCRIPT.read_text().splitlines()
    start = lines.index(f"{name}() {{")
    end = lines.index("}", start)
    return "\n".join(lines[start : end + 1])


BASH = shutil.which("bash") or "/bin/bash"


def _run(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=60)


# `sleep` and `say` are stubbed so the retry costs nothing and the loop spins;
# `compose` counts its calls in a file because the first one happens inside a
# command substitution, and a subshell's variables do not come back.
_COMPOSE_UP_HARNESS = """
set -euo pipefail
say() {{ :; }}
sleep() {{ :; }}
{function}
count=$(mktemp)
echo 0 > "$count"
compose() {{
  n=$(( $(cat "$count") + 1 ))
  echo "$n" > "$count"
  case "{mode}:$n" in
    stale:1) echo "dependency failed to start: container agenticos-redis-1 is unhealthy" >&2; return 1 ;;
    broken:*) echo "no such image: ghcr.io/vstorm-co/agenticos-backend:sha-deadbee" >&2; return 1 ;;
    *) echo "Container agenticos-app-1 Started"; return 0 ;;
  esac
}}
compose_up -f docker-compose-prod.yml >/dev/null 2>&1 && status=0 || status=$?
echo "attempts=$(cat "$count") status=$status"
"""


class TestStartingTheStackSurvivesAStaleStatus:
    def test_a_dependency_still_reporting_the_last_run_is_retried_once(self) -> None:
        result = _run(_COMPOSE_UP_HARNESS.format(function=_function("compose_up"), mode="stale"))
        assert result.stdout.strip() == "attempts=2 status=0"

    def test_any_other_failure_stops_on_the_first_attempt(self) -> None:
        """A missing image is a broken deploy, and running it twice only hides it."""
        result = _run(_COMPOSE_UP_HARNESS.format(function=_function("compose_up"), mode="broken"))
        assert result.stdout.strip() == "attempts=1 status=1"


# `date` is stubbed rather than relying on the host's: the script runs on the
# server, where it is GNU date, and what is under test here is the comparison.
_WAIT_HEALTHY_HARNESS = """
set -euo pipefail
say() {{ :; }}
sleep() {{ :; }}
date() {{ echo 1000; }}
{function}
statuses=$(mktemp)
printf '%s\\n' {statuses} > "$statuses"
compose() {{ case "$*" in *"ps -a -q"*) echo container-id ;; *) : ;; esac; }}
docker() {{
  case "$*" in
    *Health.Status*) head -1 "$statuses"; tail -n +2 "$statuses" > "$statuses.rest"; mv "$statuses.rest" "$statuses" ;;
    *StartedAt*) echo "2026-01-01T00:00:00Z" ;;
    *Health.Log*) echo "{probe}" ;;
  esac
}}
wait_healthy app -f docker-compose-prod.yml && status=0 || status=$?
echo "status=$status"
"""


class TestWaitingForHealthIgnoresAProbeFromBeforeThisStart:
    def test_a_status_left_by_the_previous_run_is_waited_through(self) -> None:
        """The probe ended before the container started, so it judges nothing here."""
        result = _run(
            _WAIT_HEALTHY_HARNESS.format(
                function=_function("wait_healthy"),
                statuses="unhealthy unhealthy healthy",
                probe="900",
            )
        )
        assert "status=0" in result.stdout
        assert "app: healthy" in result.stdout

    def test_a_probe_from_this_run_still_fails_the_deploy(self) -> None:
        result = _run(
            _WAIT_HEALTHY_HARNESS.format(
                function=_function("wait_healthy"), statuses="unhealthy", probe="1100"
            )
        )
        # `wait_healthy` ends the deploy itself rather than returning, so the
        # harness never reaches its own line.
        assert result.returncode == 1
        assert "app: unhealthy" in result.stderr
