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
"""

import re
import sys
from collections.abc import Callable
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
    paths: list[str], index: int, total: int, weight: Callable[[str], int] = lambda _: 1
) -> list[str]:
    """The paths shard `index` of `total` runs (1-based), sorted."""
    if total < 1 or not 1 <= index <= total:
        raise ValueError(f"shard {index}/{total} does not exist")
    loads = [0] * total
    chosen: list[str] = []
    for path in sorted(paths, key=lambda path: (-weight(path), path)):
        lightest = min(range(total), key=lambda shard: (loads[shard], shard))
        loads[lightest] += weight(path)
        if lightest == index - 1:
            chosen.append(path)
    return sorted(chosen)


def parse(spec: str) -> tuple[int, int]:
    """`"2/3"` -> `(2, 3)`."""
    index, separator, total = spec.partition("/")
    if not separator or not index.isdigit() or not total.isdigit():
        raise ValueError(f"expected a shard as K/N, got {spec!r}")
    return int(index), int(total)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: ci_backend_shard.py K/N TESTS_DIR", file=sys.stderr)
        return 2
    index, total = parse(argv[0])
    chosen = select(test_files(Path(argv[1])), index, total, test_count)
    if not chosen:
        # An empty list would make pytest collect the whole of `testpaths`, which
        # is the opposite of a shard.
        print(f"shard {index}/{total} selected no test files", file=sys.stderr)
        return 1
    print("\n".join(chosen))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
