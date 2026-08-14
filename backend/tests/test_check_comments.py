"""Where the banner guard walks, which is what #635 was about.

`scripts/check_comments.py` gates every commit through pre-commit and `make lint`,
and it used to walk with `Path.rglob("*")` and filter afterwards - so `SKIP_DIRS`
only decided what was *reported*, never where the walk went. On a machine with a
populated `.claude/worktrees/` (a full checkout each, `node_modules` and `.venv`
included) that was millions of paths and about seven minutes per commit. The walk
is `os.walk` with in-place pruning now, the `check_backticks.walk` shape, and
these tests hold the pruning shut from both sides: skipped names are never
descended into, and the files of this branch are still read.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "check_comments.py"
_spec = importlib.util.spec_from_file_location("check_comments_under_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check_comments = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_comments)

# Built rather than written out - a literal banner line in this file would itself
# be a finding when the guard reads its own tests.
RULE = "-" * 12
BANNER_LINE = f"#  {RULE} sending {RULE}\n"


def _walked(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in check_comments._iter_files(root)}


def test_a_banner_comment_line_is_matched() -> None:
    """The half that has to keep working, or the walk tests guard a no-op."""
    assert check_comments.BANNER.match(BANNER_LINE)


def test_files_on_this_branch_are_walked(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "conf.py").write_text(BANNER_LINE)

    assert "docs/conf.py" in _walked(tmp_path)


def test_a_nested_checkout_is_not_walked(tmp_path: Path) -> None:
    """A worktree's files belong to another branch, wherever the worktree sits.

    `.claude` in `SKIP_DIRS` covers the usual home; this covers a
    `git worktree add` pointed anywhere else.
    """
    worktree = tmp_path / "other-branch"
    worktree.mkdir()
    # What `git worktree add` leaves behind: a file, not a directory.
    (worktree / ".git").write_text("gitdir: /somewhere/.git/worktrees/other-branch\n")
    (worktree / "module.py").write_text(BANNER_LINE)

    assert not [path for path in _walked(tmp_path) if "other-branch" in path]


def test_a_skipped_directory_is_pruned_not_filtered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect itself. Filtering after `rglob` yields the same files, so the
    proof is one level down: descending is a `scandir` per directory, and none
    may happen under a skipped name (#635)."""
    dependency = tmp_path / ".claude" / "worktrees" / "wt" / "frontend" / "node_modules" / "dep"
    dependency.mkdir(parents=True)
    (dependency / "index.js").write_text("// fine\n")
    (tmp_path / "module.py").write_text(BANNER_LINE)

    real_scandir = os.scandir
    scanned: list[str] = []

    def recording_scandir(path: str | os.PathLike[str] = ".") -> object:
        scanned.append(str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", recording_scandir)
    walked = _walked(tmp_path)

    assert "module.py" in walked
    assert not [entry for entry in scanned if ".claude" in Path(entry).parts]


def test_a_root_that_itself_lives_under_a_skipped_name_is_walked(tmp_path: Path) -> None:
    """The guard runs inside worktrees too - this one included. Only the root's
    subdirectories are judged against `SKIP_DIRS`, never the root's own path."""
    root = tmp_path / ".claude" / "worktrees" / "this-branch"
    root.mkdir(parents=True)
    (root / "module.py").write_text(BANNER_LINE)

    assert "module.py" in _walked(root)
