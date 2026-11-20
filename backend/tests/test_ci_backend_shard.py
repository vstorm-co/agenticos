"""`scripts/ci_backend_shard.py` puts every backend test file in exactly one shard.

The aggregate `test` job combines whatever coverage the shards hand it, and it
cannot tell a file that ran nowhere from a file that does not exist. So the
guarantee has to hold here: the shards partition the suite, with nothing dropped
and nothing run twice.
"""

import importlib.util
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "ci_backend_shard.py"

_spec = importlib.util.spec_from_file_location("ci_backend_shard_under_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
ci_backend_shard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci_backend_shard)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "tests"
    for name in (
        "test_a.py",
        "test_b.py",
        "api/test_routes.py",
        "api/test_auth.py",
        "integration/test_db.py",
        "integration/deep/test_s3.py",
        "test_z.py",
    ):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("")
    (root / "conftest.py").write_text("")
    (root / "helpers.py").write_text("")
    (root / "api" / "fixture_test_data.json").write_text("{}")
    return root


@pytest.mark.parametrize("weighted", [False, True])
@pytest.mark.parametrize("total", [1, 2, 3, 4, 7, 10])
def test_the_shards_partition_every_test_file(tree: Path, total: int, weighted: bool) -> None:
    files = ci_backend_shard.test_files(tree)
    weight = ci_backend_shard.test_count if weighted else (lambda _: 1)
    shards = [ci_backend_shard.select(files, index, total, weight) for index in range(1, total + 1)]

    counts = Counter(path for shard in shards for path in shard)
    assert set(counts) == set(files), "a file ran in no shard"
    assert set(counts.values()) == {1}, "a file ran in more than one shard"


def test_only_test_modules_are_selected(tree: Path) -> None:
    files = ci_backend_shard.test_files(tree)

    assert len(files) == 7
    assert all(Path(path).name.startswith("test_") for path in files)


def test_paths_are_sorted_posix_strings(tree: Path) -> None:
    """The same split on every platform, because the order is the split."""
    files = ci_backend_shard.test_files(tree)

    assert files == sorted(files)
    assert all("\\" not in path for path in files)


def test_the_shards_cover_the_real_suite() -> None:
    root = REPO_ROOT / "backend" / "tests"
    files = ci_backend_shard.test_files(root)
    shards = [
        ci_backend_shard.select(files, index, 3, ci_backend_shard.test_count) for index in (1, 2, 3)
    ]

    assert sorted(path for shard in shards for path in shard) == files
    assert Path(__file__).resolve().as_posix() in files
    loads = [sum(map(ci_backend_shard.test_count, shard)) for shard in shards]
    assert max(loads) - min(loads) <= max(map(ci_backend_shard.test_count, files))


def test_a_heavy_file_is_balanced_by_many_light_ones(tmp_path: Path) -> None:
    """Shards are even in tests, not in files: the round-robin split was 19% apart."""
    (tmp_path / "test_heavy.py").write_text("def test_one(): ...\n" * 6)
    for name in "abcdef":
        (tmp_path / f"test_{name}.py").write_text("async def test_one(): ...\n")
    files = ci_backend_shard.test_files(tmp_path)

    first, second = (
        ci_backend_shard.select(files, index, 2, ci_backend_shard.test_count) for index in (1, 2)
    )

    assert first == [(tmp_path / "test_heavy.py").as_posix()]
    assert len(second) == 6


def test_a_file_without_tests_still_weighs_something(tmp_path: Path) -> None:
    (tmp_path / "test_empty.py").write_text("")

    assert ci_backend_shard.test_count(str(tmp_path / "test_empty.py")) == 1


@pytest.mark.parametrize(("index", "total"), [(0, 3), (4, 3), (1, 0)])
def test_a_shard_that_does_not_exist_is_refused(index: int, total: int) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        ci_backend_shard.select(["tests/test_a.py"], index, total)


@pytest.mark.parametrize("spec", ["1", "1/", "/3", "a/3", "1/b", "-1/3"])
def test_a_malformed_shard_is_refused(spec: str) -> None:
    with pytest.raises(ValueError, match="K/N"):
        ci_backend_shard.parse(spec)


def test_the_command_line_prints_one_shard(tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert ci_backend_shard.main(["2/3", str(tree)]) == 0

    printed = capsys.readouterr().out.splitlines()
    assert printed == ci_backend_shard.select(ci_backend_shard.test_files(tree), 2, 3)


def test_an_empty_shard_fails_rather_than_running_everything(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """pytest given no paths collects all of `testpaths`, the opposite of a shard."""
    (tmp_path / "test_only.py").write_text("")

    assert ci_backend_shard.main(["2/2", str(tmp_path)]) == 1
    assert capsys.readouterr().out == ""


def test_the_wrong_number_of_arguments_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert ci_backend_shard.main(["1/3"]) == 2
    assert "usage" in capsys.readouterr().err
