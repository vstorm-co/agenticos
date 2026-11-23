"""Distribute complete test files and refuse incomplete backend coverage evidence."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from coverage import CoverageData


def partition(root: Path, count: int) -> list[list[str]]:
    """Assign every pytest-default test file once, balancing by source size.

    File size is a deterministic initial estimate, not a runtime measurement.
    Whole files keep module fixtures together. JUnit and --durations provide
    actual timings for subsequent tuning without adding a pytest dependency.
    """
    if count < 1:
        raise ValueError("Shard count must be positive")
    files = [
        path
        for path in (root / "tests").rglob("*.py")
        if path.name.startswith("test_") or path.name.endswith("_test.py")
    ]
    shards: list[list[str]] = [[] for _ in range(count)]
    sizes = [0] * count
    for path in sorted(files, key=lambda file: (-file.stat().st_size, file.as_posix())):
        index = min(range(count), key=lambda candidate: sizes[candidate])
        shards[index].append(path.relative_to(root).as_posix())
        sizes[index] += path.stat().st_size
    # Integration paths must stay adjacent so pytest retains their conftest.
    return [sorted(shard) for shard in shards]


def run_shard(root: Path, index: int, count: int) -> int:
    """Measure a subset without applying a partial-suite coverage threshold."""
    if not 1 <= index <= count:
        raise ValueError("Shard index must be between 1 and count")
    files = partition(root, count)[index - 1]
    if not files:
        raise ValueError("Refusing an empty shard")
    reports = root / "coverage-data"
    reports.mkdir(exist_ok=True)
    destination = reports / f".coverage.{index}"
    destination.unlink(missing_ok=True)
    (root / ".coverage").unlink(missing_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *files,
            "-v",
            "--cov=app",
            "--cov-report=",
            "--cov-fail-under=0",
            "-n",
            "auto",
            "--maxprocesses",
            "4",
            "--durations=30",
            f"--junitxml={reports / f'junit-{index}.xml'}",
        ],
        cwd=root,
        check=False,
    )
    coverage = root / ".coverage"
    if coverage.exists():
        shutil.move(coverage, destination)
    return result.returncode


def check_reports(root: Path, count: int) -> None:
    """Require exactly one nonempty, readable coverage database per shard."""
    if count < 1:
        raise ValueError("Shard count must be positive")
    folder = root / "coverage-data"
    expected = {folder / f".coverage.{index}" for index in range(1, count + 1)}
    if set(folder.glob(".coverage.*")) != expected:
        raise ValueError("Missing or unexpected backend coverage shards")
    for path in sorted(expected):
        data = CoverageData(basename=str(path))
        data.read()
        if not data.measured_files():
            raise ValueError(f"Empty coverage shard: {path.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "check-reports"))
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--index", type=int, default=1)
    args = parser.parse_args()
    root = Path.cwd()
    if args.command == "run":
        return run_shard(root, args.index, args.count)
    check_reports(root, args.count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
