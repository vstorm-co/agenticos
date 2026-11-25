"""Exercise the CI restart contract without a Docker daemon."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MAKE = shutil.which("make")
assert MAKE is not None


@pytest.fixture
def docker_env(tmp_path: Path) -> dict[str, str]:
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$DOCKER_CALLS"
test "${DOCKER_UNAVAILABLE:-0}" = 0 || exit 1
case "$*" in
  *'ALTER SYSTEM SET max_locks_per_transaction = 256'*)
    test "${ALTER_FAIL:-0}" = 0 || exit 7
    echo 256 > "$LOCK_STATE" ;;
  restart*)
    test -f "$LOCK_STATE" || exit 8
    cp "$LOCK_STATE" "$RUNNING_LOCK_STATE" ;;
  *'-tAc SHOW max_locks_per_transaction')
    if test "${WRONG_READBACK:-0}" = 1; then echo 64; else cat "$RUNNING_LOCK_STATE"; fi ;;
  inspect*) exit 9 ;;
esac
"""
    )
    docker.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "CI": "true",
        "POSTGRES_CONTAINER": "disposable-test-service",
        "DOCKER_CALLS": str(tmp_path / "calls"),
        "LOCK_STATE": str(tmp_path / "locks"),
        "RUNNING_LOCK_STATE": str(tmp_path / "running-locks"),
    }


def test_restart_preserves_configuration_and_reports_storage(docker_env: dict[str, str]) -> None:
    result = subprocess.run(
        [MAKE, "ci-test-db-configure"], cwd=ROOT, env=docker_env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = Path(docker_env["DOCKER_CALLS"]).read_text()
    assert "pg_isready -q -h 127.0.0.1 -U postgres" in calls
    assert "-tAc SHOW max_locks_per_transaction" in calls
    assert "inspect --format" in calls
    assert "pg_database_size" in calls and "pg_ls_waldir" in calls
    assert "Storage diagnostic unavailable: docker" in result.stderr


@pytest.mark.parametrize("failure", ["ALTER_FAIL", "WRONG_READBACK"])
def test_configuration_failure_remains_a_failed_gate(
    docker_env: dict[str, str], failure: str
) -> None:
    result = subprocess.run(
        [MAKE, "ci-test-db-configure"],
        cwd=ROOT,
        env={**docker_env, failure: "1"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    calls = Path(docker_env["DOCKER_CALLS"]).read_text()
    assert "inspect --format" not in calls
    if failure == "ALTER_FAIL":
        assert "restart" not in calls


def test_service_measurements_run_after_success_or_failure() -> None:
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    for job_name, test_command in (("test-shard", "make test"), ("e2e-shards", "bun run test:e2e")):
        steps = jobs[job_name]["steps"]
        diagnostic = next(
            step for step in steps if step.get("run") == "make ci-test-db-diagnostics"
        )
        assert diagnostic["if"] == "${{ !cancelled() }}"
        assert diagnostic["timeout-minutes"] == 2
        assert diagnostic["env"]["POSTGRES_CONTAINER"] == "${{ job.services.postgres.id }}"
        assert steps.index(diagnostic) > next(
            index
            for index, step in enumerate(steps)
            if step.get("run", "").startswith(test_command)
        )


@pytest.mark.parametrize("override", [{"CI": "false"}, {"POSTGRES_CONTAINER": ""}])
def test_configuration_requires_the_ci_service(
    docker_env: dict[str, str], override: dict[str, str]
) -> None:
    result = subprocess.run(
        [MAKE, "ci-test-db-configure"],
        cwd=ROOT,
        env={**docker_env, **override},
        capture_output=True,
    )
    assert result.returncode != 0
    assert not Path(docker_env["DOCKER_CALLS"]).exists()


def test_crashed_service_still_reports_host_capacity(docker_env: dict[str, str]) -> None:
    result = subprocess.run(
        [MAKE, "ci-test-db-diagnostics"],
        cwd=ROOT,
        env={**docker_env, "DOCKER_UNAVAILABLE": "1"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.count("Filesystem") == 2
    assert result.stderr.count("Storage diagnostic unavailable: docker") == 3
