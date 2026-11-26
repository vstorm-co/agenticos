"""Complete test-file distribution and real merged coverage retain the gate."""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest
import yaml
from coverage import CoverageData
from coverage.exceptions import DataError

ROOT = Path(__file__).resolve().parents[2]
make_path = shutil.which("make")
assert make_path is not None
MAKE: Final[str] = make_path
spec = importlib.util.spec_from_file_location(
    "ci_backend_shards", ROOT / "scripts/ci_backend_shards.py"
)
assert spec is not None and spec.loader is not None
shards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shards)


def test_partition_is_complete_disjoint_and_deterministic(tmp_path: Path) -> None:
    files = {
        "tests/test_a.py",
        "tests/api/test_b.py",
        "tests/integration/test_c.py",
        "tests/d_test.py",
    }
    for name in files | {"tests/conftest.py", "tests/helpers.py"}:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# test source\n" * len(name))
    first = shards.partition(tmp_path, 3)
    assert first == shards.partition(tmp_path, 3)
    flat = [path for shard in first for path in shard]
    assert set(flat) == files
    assert len(flat) == len(files)
    assert all(shard == sorted(shard) for shard in first)


@pytest.mark.parametrize("index,count", [(0, 4), (5, 4), (1, 0), (1, -1), (1, 4)])
def test_invalid_or_empty_shards_cannot_report_success(
    tmp_path: Path, index: int, count: int
) -> None:
    with pytest.raises(ValueError):
        shards.run_shard(tmp_path, index, count)


@pytest.mark.parametrize("problem", ["missing", "extra", "empty", "corrupt"])
def test_incomplete_coverage_evidence_is_refused(tmp_path: Path, problem: str) -> None:
    folder = tmp_path / "coverage-data"
    folder.mkdir()
    for index in range(1, 5):
        data = CoverageData(basename=str(folder / f".coverage.{index}"))
        data.add_lines({"app/module.py": {1}})
        data.write()
    path = folder / ".coverage.4"
    if problem == "missing":
        path.unlink()
    elif problem == "extra":
        shutil.copy(path, folder / ".coverage.5")
    else:
        path.write_text("" if problem == "empty" else "invalid coverage data")
    with pytest.raises((ValueError, DataError)):
        shards.check_reports(tmp_path, 4)


@pytest.mark.parametrize("uncovered", [False, True])
def test_real_shards_combine_before_the_unchanged_gate(tmp_path: Path, uncovered: bool) -> None:
    shutil.copy(ROOT / "Makefile", tmp_path / "Makefile")
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/ci_backend_shards.py", tmp_path / "scripts")
    backend = tmp_path / "backend"
    (backend / "tests").mkdir(parents=True)
    (backend / "app").mkdir()
    (backend / "app/__init__.py").write_text("")
    for index in range(4):
        (backend / f"app/module{index}.py").write_text(f"def value():\n    return {index}\n")
        (backend / f"tests/test_module{index}.py").write_text(
            f"from app.module{index} import value\ndef test_value():\n    assert value() == {index}\n"
        )
    if uncovered:
        with (backend / "app/module0.py").open("a") as stream:
            stream.write("def uncovered():\n    return -1\n")
    (backend / "pyproject.toml").write_text(
        '[project]\nname="shard-contract"\nversion="0.0.0"\n'
        '[tool.pytest.ini_options]\npythonpath=["."]\n'
        '[tool.coverage.run]\nrelative_files=true\ninclude=["app/**"]\nbranch=true\n'
        "[tool.coverage.report]\nfail_under=100\n"
    )
    env = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": sys.prefix,
        "UV_NO_SYNC": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTEST_PLUGINS": "pytest_cov.plugin,xdist.plugin",
        "PYTEST_XDIST_AUTO_NUM_WORKERS": "1",
    }
    for index in range(1, 5):
        run = subprocess.run(
            [MAKE, "test-backend-shard", "TEST_DB=external", f"BACKEND_SHARD={index}"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stdout + run.stderr
    result = subprocess.run(
        [MAKE, "test-backend-merge"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is not uncovered, result.stdout + result.stderr
    assert (backend / "coverage.xml").exists()


@pytest.mark.parametrize("status", ["failure", "cancelled", "skipped", "", "success"])
def test_aggregate_refuses_failed_or_skipped_shards(status: str) -> None:
    result = subprocess.run(
        [MAKE, "test-backend-jobs-check"],
        cwd=ROOT,
        env={**os.environ, "TESTS": status},
        capture_output=True,
    )
    assert (result.returncode == 0) is (status == "success")


def test_backend_shards_have_independent_services_and_fail_closed_aggregate() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    jobs = workflow["jobs"]
    assert jobs["backend-shards"]["strategy"]["matrix"]["shard"] == [1, 2, 3, 4]
    assert jobs["backend-shards"]["strategy"]["fail-fast"] is False
    assert set(jobs["backend-shards"]["services"]) == {"postgres", "redis"}
    assert "backend-shards" in jobs["test"]["needs"]
    assert "!cancelled()" in jobs["test"]["if"]
    steps = jobs["test"]["steps"]
    names = [step.get("name") for step in steps]
    assert names.index("Require every backend shard to have succeeded") < names.index(
        "Apply the unchanged coverage gate to the complete backend suite"
    )


@pytest.mark.parametrize("filename", ["ci.yml", "codeql.yml"])
def test_leaving_draft_starts_heavy_checks_and_returning_cancels_them(filename: str) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())
    assert set(workflow[True]["pull_request"]["types"]) >= {
        "opened",
        "synchronize",
        "reopened",
        "ready_for_review",
        "converted_to_draft",
    }
    jobs = (
        [
            "backend-shards",
            "test",
            "frontend-shards",
            "build-frontend",
            "test-frontend",
            "e2e-shards",
            "e2e",
            "docs",
        ]
        if filename == "ci.yml"
        else ["analyze"]
    )
    for name in jobs:
        assert (
            "(github.event_name != 'pull_request' || !github.event.pull_request.draft)"
            in workflow["jobs"][name]["if"]
        )
    assert (
        workflow["concurrency"]["cancel-in-progress"]
        == "${{ github.event_name == 'pull_request' }}"
    )
    if filename == "ci.yml":
        for name in ("lint", "lint-frontend", "security"):
            assert "draft" not in workflow["jobs"][name].get("if", "")
