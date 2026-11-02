"""Parallel CI keeps complete coverage and required checks fail closed."""

import itertools
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MAKE = shutil.which("make")
BASH = shutil.which("bash")
assert MAKE is not None and BASH is not None


@pytest.mark.parametrize("status", ["failure", "cancelled", "skipped", ""])
@pytest.mark.parametrize("job", ["LINT", "BUILD", "TESTS"])
def test_frontend_aggregate_refuses_an_unsuccessful_dependency(job: str, status: str) -> None:
    env = {**os.environ, "LINT": "success", "BUILD": "success", "TESTS": "success", job: status}
    result = subprocess.run(
        [MAKE, "test-frontend-jobs-check"], cwd=ROOT, env=env, capture_output=True, text=True
    )
    assert result.returncode != 0


def test_frontend_aggregate_accepts_complete_success() -> None:
    result = subprocess.run(
        [MAKE, "test-frontend-jobs-check"],
        cwd=ROOT,
        env={**os.environ, "LINT": "success", "BUILD": "success", "TESTS": "success"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("missing", [None, 1, 2, 3, 4])
def test_report_check_refuses_a_missing_shard(tmp_path: Path, missing: int | None) -> None:
    shutil.copy(ROOT / "Makefile", tmp_path / "Makefile")
    folder = tmp_path / "frontend/.vitest-reports"
    folder.mkdir(parents=True)
    for shard in range(1, 5):
        if shard != missing:
            (folder / f"blob-{shard}-4.json").write_text("test report")
    result = subprocess.run(
        [MAKE, "test-frontend-reports-check"], cwd=tmp_path, capture_output=True
    )
    assert (result.returncode == 0) is (missing is None)


@pytest.mark.parametrize("failure", ["none", "test", "platform", "unimported"])
def test_one_backend_run_preserves_the_platform_gate(tmp_path: Path, failure: str) -> None:
    """Exercise the actual Makefile against real pytest/coverage on a tiny application."""
    shutil.copy(ROOT / "Makefile", tmp_path / "Makefile")
    backend = tmp_path / "backend"
    (backend / "app").mkdir(parents=True)
    (backend / "tests").mkdir()
    (backend / "app/__init__.py").write_text("")
    (backend / "app/platform.py").write_text("def value():\n    return 1\n")
    (backend / "app/inherited.py").write_text("def never_called():\n    return 2\n")
    if failure == "platform":
        with (backend / "app/platform.py").open("a") as stream:
            stream.write("def uncovered():\n    return 3\n")
    imported = "" if failure == "unimported" else "from app.platform import value\n"
    assertion = (
        "assert False"
        if failure == "test"
        else "assert True"
        if failure == "unimported"
        else "assert value() == 1"
    )
    (backend / "tests/test_example.py").write_text(
        imported
        + "from pathlib import Path\ndef test_value():\n"
        + "    Path('executed').write_text('one run')\n    "
        + assertion
        + "\n"
    )
    (backend / "pyproject.toml").write_text(
        '[project]\nname="coverage-contract"\nversion="0.0.0"\n'
        '[tool.pytest.ini_options]\npythonpath=["."]\n'
        '[tool.coverage.run]\ninclude=["app/platform.py"]\n'
        "[tool.coverage.report]\nfail_under=100\nshow_missing=true\n"
    )
    env = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": sys.prefix,
        "UV_NO_SYNC": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTEST_PLUGINS": "pytest_cov.plugin,xdist.plugin",
    }
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [MAKE, "test", "TEST_DB=external", "COV_REPORT=xml"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is (failure == "none"), result.stdout + result.stderr
    assert (backend / "coverage.xml").exists()
    xml = (backend / "coverage.xml").read_text()
    assert "inherited.py" not in xml
    if failure != "none":
        return
    (backend / "executed").unlink()
    report = subprocess.run(
        [MAKE, "coverage-all", "REUSE_COVERAGE=1", "TEST_DB=external"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert report.returncode == 0, report.stdout + report.stderr
    assert "inherited.py" in report.stdout
    assert not (backend / "executed").exists(), "informational report ran tests again"


def test_shards_preserve_required_contexts_and_isolation() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    jobs = workflow["jobs"]
    for name in ("frontend-shards", "e2e-shards"):
        assert jobs[name]["strategy"]["matrix"]["shard"] == [1, 2, 3, 4]
        assert jobs[name]["strategy"]["fail-fast"] is False
    for name, dependency in (("test-frontend", "frontend-shards"), ("e2e", "e2e-shards")):
        assert dependency in jobs[name]["needs"]
        assert "!cancelled()" in jobs[name]["if"]
        step = (
            jobs[name]["steps"][-1]
            if name == "e2e"
            else next(
                step
                for step in jobs[name]["steps"]
                if step.get("name") == "Require every frontend job to have succeeded"
            )
        )
        for statuses in itertools.product(("success", "failure", "skipped"), repeat=2):
            env = {**os.environ, "BUILD": statuses[0], "TESTS": statuses[1], "LINT": "success"}
            result = subprocess.run(
                [BASH, "-c", step["run"]], cwd=ROOT, env=env, capture_output=True
            )
            assert (result.returncode == 0) is (statuses == ("success", "success"))
    assert set(jobs["e2e-shards"]["services"]) == {"postgres", "redis"}
    assert "build-frontend" in jobs["e2e-shards"]["needs"]
    for name in ("test", "e2e-shards"):
        postgres = jobs[name]["services"]["postgres"]
        assert postgres["image"] == "pgvector/pgvector:pg16"
        assert "--tmpfs /var/lib/postgresql/data" in postgres["options"]


def test_cancelled_runs_do_not_recollect_tests_for_informational_reports() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    reports = {
        "Report coverage of template-inherited code",
        "Report the security refusal tests",
        "Upload the security refusal-test list",
    }
    steps = workflow["jobs"]["test"]["steps"]
    selected = [step for step in steps if step.get("name") in reports]
    assert len(selected) == len(reports)
    assert all(step["if"] == "${{ !cancelled() }}" for step in selected)
