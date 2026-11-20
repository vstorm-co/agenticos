#!/usr/bin/env python3
"""The backend test files one CI shard runs.

    python ../scripts/ci_backend_shard.py 2/3 tests

prints, one per line, the `test_*.py` files under `tests` that shard 2 of 3 runs.
`make test` passes that list to pytest when
`BACKEND_SHARD` is set, and the `test` job in `ci.yml` combines the three coverage
files the shards leave behind before it applies the platform gate.

The split is by file, and deterministic, on purpose. pytest-xdist already balances
tests across the workers inside one shard; what this has to guarantee is the thing
the aggregate gate cannot check afterwards - that every file runs in exactly one
shard. A plugin that splits by recorded duration balances better and decides
membership from a cache file, which is a second input that can drift. So the
weight of a file is read from the tree itself: the number of test functions it
defines. Files are dealt heaviest first, each to the shard with the least weight
so far (ties to the lower path, then the lower shard), which keeps the shards'
test counts within a few percent of each other. Round-robin over the sorted paths,
the first version, dealt files evenly but tests unevenly - one shard held 19% more
tests than another.

Paths are sorted as POSIX strings so the order, and therefore the split, is the same
on every platform.

Recorded times (2026-11-21). Test counts left the shards at 1029 / 523 / 917 s of
test time. When `BACKEND_SHARD_TIMES` names a JSON map of file -> seconds, recorded
by the last green full run and handed to all three shards by the `changes` job,
a file weighs its recorded seconds; a file with no record weighs its test count
times the suite's mean seconds per test. Every shard reads the same file, so the
split is still one deterministic function of the tree plus that one input, and
`verify` (run by the aggregate `test` job) proves the shards together ran every
file exactly once.

    python ../scripts/ci_backend_shard.py times junit-shard*.xml > file-times.json
    python ../scripts/ci_backend_shard.py verify tests shard1.txt shard2.txt shard3.txt
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable, Mapping
from pathlib import Path

_TEST_FUNCTION = re.compile(r"^\s*(?:async\s+)?def\s+test", re.MULTILINE)


def test_files(root: Path) -> list[str]:
    """Every pytest-discoverable test module under `root`, sorted."""
    return sorted(path.as_posix() for path in root.rglob("test_*.py"))


def test_count(path: str) -> int:
    """How many test functions `path` defines, and at least 1: the file's weight."""
    source = Path(path).read_text(encoding="utf-8")
    return max(1, len(_TEST_FUNCTION.findall(source)))


def select(
    paths: list[str], index: int, total: int, weight: Callable[[str], float] = lambda _: 1
) -> list[str]:
    """The paths shard `index` of `total` runs (1-based), sorted."""
    if total < 1 or not 1 <= index <= total:
        raise ValueError(f"shard {index}/{total} does not exist")
    loads = [0.0] * total
    chosen: list[str] = []
    for path in sorted(paths, key=lambda path: (-weight(path), path)):
        lightest = min(range(total), key=lambda shard: (loads[shard], shard))
        loads[lightest] += weight(path)
        if lightest == index - 1:
            chosen.append(path)
    return sorted(chosen)


def recorded_weight(times: Mapping[str, float]) -> Callable[[str], float]:
    """A file's recorded seconds; an unrecorded file is estimated from its test count."""
    counted = [path for path in times if Path(path).is_file()]
    tests = sum(test_count(path) for path in counted)
    per_test = sum(times[path] for path in counted) / tests if tests else 1.0

    def weight(path: str) -> float:
        if path in times:
            return max(float(times[path]), 0.001)
        return test_count(path) * per_test

    return weight


def load_times(path: str | None) -> dict[str, float]:
    """The recorded times, or none at all when the file is absent, empty or unreadable."""
    if not path or not Path(path).is_file():
        return {}
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {
        str(key): float(value) for key, value in loaded.items() if isinstance(value, int | float)
    }


def file_times(reports: list[str], files: list[str]) -> dict[str, float]:
    """Seconds per test file, summed from JUnit reports' test cases."""
    modules = {path.removesuffix(".py").replace("/", "."): path for path in files}
    totals: dict[str, float] = {}
    for report in reports:
        # The reports are pytest's own JUnit output from this workflow's shards.
        for case in ElementTree.parse(report).iter("testcase"):  # noqa: S314
            classname = case.get("classname", "")
            parts = classname.split(".")
            for end in range(len(parts), 0, -1):
                path = modules.get(".".join(parts[:end]))
                if path:
                    totals[path] = totals.get(path, 0.0) + float(case.get("time") or 0)
                    break
    return {path: round(seconds, 3) for path, seconds in sorted(totals.items())}


def verify(files: list[str], shards: list[list[str]]) -> list[str]:
    """Every problem with `shards` as a partition of `files`; empty when it is one."""
    ran = [path for shard in shards for path in shard]
    problems = [f"{path} ran in no shard" for path in sorted(set(files) - set(ran))]
    problems += [
        f"{path} ran in {ran.count(path)} shards"
        for path in sorted(set(ran))
        if ran.count(path) > 1
    ]
    problems += [f"{path} is not a test file" for path in sorted(set(ran) - set(files))]
    return problems


def parse(spec: str) -> tuple[int, int]:
    """`"2/3"` -> `(2, 3)`."""
    index, separator, total = spec.partition("/")
    if not separator or not index.isdigit() or not total.isdigit():
        raise ValueError(f"expected a shard as K/N, got {spec!r}")
    return int(index), int(total)


def main(argv: list[str]) -> int:
    if argv[:1] == ["times"] and len(argv) > 1:
        root = Path(os.environ.get("BACKEND_TESTS_DIR", "tests"))
        print(json.dumps(file_times(argv[1:], test_files(root)), indent=1, sort_keys=True))
        return 0
    if argv[:1] == ["verify"] and len(argv) > 2:
        lists = [Path(path).read_text(encoding="utf-8").split() for path in argv[2:]]
        problems = verify(test_files(Path(argv[1])), lists)
        print(
            "\n".join(problems) or f"{sum(map(len, lists))} files, each in exactly one shard",
            file=sys.stderr,
        )
        return 1 if problems else 0
    if len(argv) != 2:
        print("usage: ci_backend_shard.py K/N TESTS_DIR", file=sys.stderr)
        return 2
    index, total = parse(argv[0])
    times = load_times(os.environ.get("BACKEND_SHARD_TIMES"))
    weight = recorded_weight(times) if times else test_count
    chosen = select(test_files(Path(argv[1])), index, total, weight)
    if not chosen:
        # An empty list would make pytest collect the whole of `testpaths`, which
        # is the opposite of a shard.
        print(f"shard {index}/{total} selected no test files", file=sys.stderr)
        return 1
    print("\n".join(chosen))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
