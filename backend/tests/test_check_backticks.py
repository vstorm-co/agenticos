"""Where the backtick guard looks, and the two ways that has been wrong.

`scripts/check_backticks.py` gates every commit and every `make lint`, and it walks
the tree rather than a file list. Both failures so far were about *where* it walked.

It used to descend into `.claude/worktrees/`, which holds a full checkout per branch.
So `make lint` reported three findings on line 170 of a file nobody had edited - the
copy of this very script living in each worktree, whose error message has to spell the
pattern out - and no commit could be made with a worktree open (#225).

Skipping every directory named `worktrees` stopped that and traded it for the quieter
mistake: a `docs/worktrees/` that is only a directory with a name would be dropped
from the scan, and a worktree placed anywhere else would still be walked. So the rule
is now what it always meant - **do not descend into another checkout** - and both
halves are asserted here, because a guard that silently reads less than it claims is
the failure mode this file exists to catch.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "check_backticks.py"
_spec = importlib.util.spec_from_file_location("check_backticks_under_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check_backticks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_backticks)

# Built rather than quoted. This file is scanned by the guard it tests, so a literal
# span here would be a finding in `make lint` - the same reason the script exempts
# itself and every copy of itself.
TICKS = "`" * 2
OFFENDING_LINE = f"See {TICKS}--fix{TICKS} for the flag.\n"


def _tree(root: Path) -> None:
    """A checkout with a worktree under it, both holding an offending line."""
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "guide.md").write_text(OFFENDING_LINE)

    worktree = root / ".claude" / "worktrees" / "other-branch"
    (worktree / "docs").mkdir(parents=True)
    # What `git worktree add` leaves behind: a file, not a directory.
    (worktree / ".git").write_text("gitdir: /somewhere/.git/worktrees/other-branch\n")
    (worktree / "docs" / "guide.md").write_text(OFFENDING_LINE)
    (worktree / "scripts").mkdir()
    (worktree / "scripts" / "check_backticks.py").write_text(_SCRIPT.read_text())


def _walked(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in check_backticks.walk([root])}


def test_a_double_backtick_span_in_prose_is_reported(tmp_path: Path) -> None:
    """The half that has to keep working, or the rest of this is a green no-op."""
    sample = tmp_path / "guide.md"
    sample.write_text(OFFENDING_LINE)

    assert check_backticks.scan(sample) == [(1, OFFENDING_LINE.rstrip("\n"))]


def test_a_fenced_block_is_not_prose(tmp_path: Path) -> None:
    """A code fence renders literally on purpose; rewriting one would corrupt it."""
    sample = tmp_path / "guide.md"
    sample.write_text(f"```\nrun with {TICKS}--fix{TICKS}\n```\n")

    assert check_backticks.scan(sample) == []


def test_this_branch_is_walked(tmp_path: Path) -> None:
    _tree(tmp_path)

    assert "docs/guide.md" in _walked(tmp_path)


def test_a_worktree_is_not_walked(tmp_path: Path) -> None:
    """Another branch's files, and a copy of this script that names the pattern.

    Neither belongs in this branch's report: the findings are not on this branch, and
    the copy's own error message is not a defect in anything.
    """
    _tree(tmp_path)

    assert not [path for path in _walked(tmp_path) if "other-branch" in path]


def test_a_directory_merely_called_worktrees_is_still_walked(tmp_path: Path) -> None:
    """The other half. An exclusion by name reads less of the tree than it says.

    `docs/worktrees/notes.md` is prose in this checkout, on this branch, and a guard
    that skips it because of the directory's name is one that reports "no double
    backticks" about a file it never opened.
    """
    (tmp_path / "docs" / "worktrees").mkdir(parents=True)
    (tmp_path / "docs" / "worktrees" / "notes.md").write_text(OFFENDING_LINE)

    assert "docs/worktrees/notes.md" in _walked(tmp_path)


def test_a_copy_of_this_script_is_exempt_even_when_named_directly(tmp_path: Path) -> None:
    """`--fix` on a copy would rewrite the pattern it exists to detect.

    The exemption used to be one absolute path, so every copy was a finding; it is
    the file's name now.
    """
    copy = tmp_path / "check_backticks.py"
    copy.write_text(_SCRIPT.read_text())

    assert check_backticks.scan(copy) == []
