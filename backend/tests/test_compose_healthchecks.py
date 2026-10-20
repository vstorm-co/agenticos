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

import re
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


@pytest.mark.parametrize("file_name", ["docker-compose.yml", "docker-compose-dev.yml"])
def test_the_browser_shares_a_network_only_with_what_drives_it(file_name: str) -> None:
    """A page the browser is sent to - or redirected to - must not reach Postgres,
    Redis or MinIO (Codex review of #2062). It sits on a network of its own,
    which only the API and the worker join to reach its DevTools port - and
    its egress proxy, the way out it is given, which joins nothing else."""
    services = _services(file_name)

    def networks(name: str) -> set[str]:
        declared = services[name].get("networks", [])
        return set(declared if isinstance(declared, list) else declared.keys())

    assert networks("browser") == {"browser"}
    assert networks("browser-egress") == {"browser"}
    on_it = {name for name in services if "browser" in networks(name)}
    assert on_it == {"browser", "browser-egress", "app", "worker"}


@pytest.mark.security
@pytest.mark.parametrize("compose_file", ["docker-compose.yml", "docker-compose-dev.yml"])
def test_the_browser_goes_out_through_the_egress_proxy_by_default(compose_file: str) -> None:
    """Codex on #2062: the proxy service existed and nothing selected it.

    Whatever drives the shared browser - the API for a live browse, the worker
    for a scheduled one - starts it behind `browser-egress` unless the root
    `.env` says otherwise.
    """
    services = yaml.safe_load((REPO_ROOT / compose_file).read_text())["services"]

    assert "browser-egress" in services
    for name in ("app", "worker"):
        environment = services[name]["environment"]
        assert (
            "BROWSER_EGRESS_PROXY=${BROWSER_EGRESS_PROXY-http://browser-egress:3128}" in environment
        ), name


_STANDARD_PROBE_MODULES = {"urllib.request", "os", "sys", "time"}
"""What a probe may import: an HTTP check needs `urllib`, the worker's file check the rest."""


@pytest.mark.parametrize("file_name", COMPOSE_FILES)
def test_a_python_probe_imports_only_the_standard_library(file_name: str) -> None:
    """Each probe is a fresh interpreter every 15-30s. Importing httpx doubled
    what one cost on the production host - 956 ms against 431 ms with `urllib` -
    on a machine already short of CPU (#2228)."""
    probes = [
        (name, " ".join(service["healthcheck"]["test"]))
        for name, service in _services(file_name).items()
        if "healthcheck" in service and service["healthcheck"]["test"][1:2] == ["python"]
    ]
    assert probes, f"{file_name}: no Python probe - the parametrization is stale"
    for name, probe in probes:
        imported = {
            module.strip()
            for statement in re.findall(r"import ([\w., ]+?);", probe)
            for module in statement.split(",")
        }
        assert imported, f"{file_name}: {name} probes with {probe}"
        assert imported <= _STANDARD_PROBE_MODULES, f"{file_name}: {name} imports {imported}"


@pytest.mark.parametrize(
    "file_name", ["docker-compose-prod.yml", "docker-compose-prod.frontend.yml"]
)
def test_every_production_service_caps_its_log(file_name: str) -> None:
    """Docker keeps a `json-file` log until the container is removed, and nothing
    on the host rotates it: prod held 570 MB and growing (#2228)."""
    for name, service in _services(file_name).items():
        options = (service.get("logging") or {}).get("options") or {}
        assert options.get("max-size") and options.get("max-file"), (
            f"{file_name}: {name} logs without a cap"
        )


_PREPARE_HARNESS = """
set -euo pipefail
say() {{ echo "say: $*"; }}
{function}
compose() {{
  echo "compose $*"
  [ "{mode}" = ok ]
}}
prepare_sandbox_runtimes {args} 2>&1 && echo "status=0" || echo "status=$?"
"""


class TestTheSandboxRuntimesArePreparedBeforeTheSwitch:
    """#2222: a release that changed a runtime made the first sandboxed chat wait
    minutes on a build. The deploy builds the images in a one-off container of
    the new sandboxd image before the old service is replaced."""

    def _run(self, *, args: str, mode: str = "ok") -> str:
        return _run(
            _PREPARE_HARNESS.format(
                function=_function("prepare_sandbox_runtimes"), args=args, mode=mode
            )
        ).stdout

    def test_it_runs_the_librarys_prepare_in_a_one_off_container(self) -> None:
        out = self._run(args="-f docker-compose-prod.yml --profile sandbox")

        assert (
            "compose -f docker-compose-prod.yml --profile sandbox run --rm --no-deps -T "
            "sandboxd python -m pydantic_ai_backends.remote.prepare"
        ) in out
        assert out.strip().endswith("status=0")

    def test_a_runtime_it_cannot_prepare_does_not_fail_the_deploy(self) -> None:
        """The service still builds it when a session asks - the old behaviour,
        said out loud instead of silently."""
        out = self._run(args="-f docker-compose-prod.yml --profile sandbox", mode="fail")

        assert "Not every sandbox runtime is prepared" in out
        assert out.strip().endswith("status=0")

    def test_a_host_without_the_sandbox_has_nothing_to_prepare(self) -> None:
        out = self._run(args="-f docker-compose-prod.yml")

        assert "compose" not in out
        assert out.strip() == "status=0"

    def test_the_deploy_prepares_after_pulling_and_before_starting(self) -> None:
        script = DEPLOY_SCRIPT.read_text()
        pull = script.index("pull --quiet\n")
        prepare = script.index('prepare_sandbox_runtimes "${BACKEND[@]}"')
        start = script.index('compose_up "${BACKEND[@]}"')

        assert pull < prepare < start


_RETIRE_HARNESS = """
set -euo pipefail
APP_DIR=/opt/agenticos
say() {{ echo "say: $*"; }}
{retired}
{function}
docker() {{
  echo "docker $*" >&2
  case "$*" in
    *"service=prefect-runner"*) [ "{mode}" = present ] && echo abc123 ;;
  esac
  return 0
}}
retire_services
"""


class TestTheRetiredServicesAreRemovedBeforeTheWorkerStarts:
    """Codex on #2248: compose leaves a service that left the file running, and an
    upgraded host kept Prefect's scheduler dispatching the old work beside the
    worker that replaced it."""

    def _run(self, mode: str) -> str:
        script = DEPLOY_SCRIPT.read_text()
        retired = next(line for line in script.splitlines() if line.startswith("RETIRED_SERVICES="))
        done = _run(
            _RETIRE_HARNESS.format(
                retired=retired, function=_function("retire_services"), mode=mode
            )
        )
        # The stub logs on stderr: its stdout is the ids `$(...)` reads back.
        return done.stdout + done.stderr

    def test_a_retired_container_of_this_project_is_removed(self) -> None:
        out = self._run("present")

        assert (
            "docker ps -aq --filter label=com.docker.compose.project.working_dir=/opt/agenticos "
            "--filter label=com.docker.compose.service=prefect-runner"
        ) in out
        assert "say: Removing the retired prefect-runner" in out
        assert "docker rm -f abc123" in out
        assert "prefect-server" in out and "Removing the retired prefect-server" not in out

    def test_a_host_that_never_ran_them_removes_nothing(self) -> None:
        assert "docker rm" not in self._run("absent")

    def test_they_are_removed_before_the_api_and_worker_start(self) -> None:
        script = DEPLOY_SCRIPT.read_text()
        assert script.index("\nretire_services\n") < script.index('compose_up "${BACKEND[@]}"')
