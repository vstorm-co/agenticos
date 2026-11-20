"""`scripts/ci_backend_shard.py` puts every backend test file in exactly one shard.

The aggregate `test` job combines whatever coverage the shards hand it, and it
cannot tell a file that ran nowhere from a file that does not exist. So the
guarantee has to hold here: the shards partition the suite, with nothing dropped
and nothing run twice.
"""

import importlib.util
import json
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


def test_recorded_times_balance_the_shards_better_than_test_counts(tmp_path: Path) -> None:
    """One slow file outweighs many quick ones once its seconds are known (2026-11-21)."""
    for name in ("slow", "quick_a", "quick_b", "quick_c"):
        (tmp_path / f"test_{name}.py").write_text("def test_one(): ...\ndef test_two(): ...\n")
    files = ci_backend_shard.test_files(tmp_path)
    times = {
        str(tmp_path / "test_slow.py"): 90.0,
        **{str(tmp_path / f"test_quick_{x}.py"): 10.0 for x in "abc"},
    }

    shards = [
        ci_backend_shard.select(files, i, 2, ci_backend_shard.recorded_weight(times))
        for i in (1, 2)
    ]

    assert [str(tmp_path / "test_slow.py")] in shards


def test_an_unrecorded_file_is_estimated_from_its_test_count(tmp_path: Path) -> None:
    (tmp_path / "test_known.py").write_text("def test_one(): ...\ndef test_two(): ...\n")
    (tmp_path / "test_new.py").write_text("def test_one(): ...\n" * 3)
    weight = ci_backend_shard.recorded_weight({str(tmp_path / "test_known.py"): 8.0})

    assert weight(str(tmp_path / "test_known.py")) == 8.0
    assert weight(str(tmp_path / "test_new.py")) == 12.0


@pytest.mark.parametrize("content", [None, "", "not json", "[1, 2]"])
def test_missing_or_unreadable_times_mean_no_times(tmp_path: Path, content: str | None) -> None:
    path = tmp_path / "times.json"
    if content is not None:
        path.write_text(content)

    assert ci_backend_shard.load_times(str(path)) == {}


def test_the_times_change_the_split_but_never_the_partition(
    tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    files = ci_backend_shard.test_files(tree)
    times = tmp_path / "times.json"
    times.write_text(json.dumps({path: float(len(path)) for path in files}))
    monkeypatch.setenv("BACKEND_SHARD_TIMES", str(times))
    shards = []
    for index in (1, 2, 3):
        assert ci_backend_shard.main([f"{index}/3", str(tree)]) == 0
        shards.append(capsys.readouterr().out.split())

    assert ci_backend_shard.verify(files, shards) == []


def test_verify_names_a_dropped_a_doubled_and_a_foreign_file() -> None:
    problems = ci_backend_shard.verify(
        ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"],
        [["tests/test_a.py", "tests/test_x.py"], ["tests/test_a.py"]],
    )

    assert problems == [
        "tests/test_b.py ran in no shard",
        "tests/test_c.py ran in no shard",
        "tests/test_a.py ran in 2 shards",
        "tests/test_x.py is not a test file",
    ]


def test_the_verify_command_fails_on_a_broken_partition(tree: Path, tmp_path: Path) -> None:
    files = ci_backend_shard.test_files(tree)
    whole, short = tmp_path / "whole.txt", tmp_path / "short.txt"
    whole.write_text("\n".join(files))
    short.write_text("\n".join(files[1:]))

    assert ci_backend_shard.main(["verify", str(tree), str(whole)]) == 0
    assert ci_backend_shard.main(["verify", str(tree), str(short)]) == 1


def test_junit_times_are_summed_per_file(tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(
        "<testsuites><testsuite>"
        '<testcase classname="tests.api.test_routes" name="test_one" time="1.5"/>'
        '<testcase classname="tests.test_a.TestThing" name="test_two" time="2.25"/>'
        '<testcase classname="tests.test_a" name="test_three" time="1"/>'
        '<testcase classname="tests.test_gone" name="test_four" time="9"/>'
        "</testsuite></testsuites>"
    )

    assert ci_backend_shard.file_times(
        [str(report)], ["tests/api/test_routes.py", "tests/test_a.py"]
    ) == {
        "tests/api/test_routes.py": 1.5,
        "tests/test_a.py": 3.25,
    }
