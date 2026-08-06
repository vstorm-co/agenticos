"""The i18n guard refuses a count built the English way, `{n} runs`.

`scripts/check_i18n.py` is what keeps every user-facing string in the catalog and
out of the components; the rule survives only as long as something checks it. Its
`MIXED` sweep counted the words left after removing the interpolation and fired at
two or more - so `Owned by {email}` was caught but `{n} runs`, one word past the
interpolation, was not. That is exactly the shape a count takes, and it is the one
shape English builds by suffixing an `s` that no other locale can: Polish declines
the noun, so `1 runs` never becomes `1 run` and cannot agree with the number at all.

The `COUNT` rule closes that gap. This test is the regression guard the rule needs:
a gate whose failure mode is a green build needs something checking the checker.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "check_i18n.py"
_spec = importlib.util.spec_from_file_location("check_i18n_under_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check_i18n = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_i18n)


def _offences(tmp_path: Path, source: str) -> list[tuple[int, str]]:
    sample = tmp_path / "sample.tsx"
    sample.write_text(source)
    return check_i18n.offences(sample)


def test_a_count_built_as_expr_word_is_refused(tmp_path: Path) -> None:
    found = _offences(tmp_path, '<span className="x">{entry.run_count} runs</span>\n')
    assert [what for _, what in found if what.startswith("count ")], found


def test_the_icu_plural_call_that_replaces_it_is_not_read_as_a_count(tmp_path: Path) -> None:
    # The fix - a `plural` message read through `t()` - must pass, or the rule would
    # forbid its own remedy. The nested `{ count: … }` argument is the trap: a naive
    # rule reads it as a second interpolation with a trailing word.
    found = _offences(tmp_path, '<span>{t("runCount", { count: entry.run_count })}</span>\n')
    assert found == [], found


def test_a_conditional_that_renders_a_word_is_not_a_count(tmp_path: Path) -> None:
    # `{show && <Icon />} more` is a guard, not a count: the element in the
    # interpolation is what tells the two apart, and the rule must not confuse them.
    found = _offences(tmp_path, "<div>{show && <Icon />} more</div>\n")
    assert not [what for _, what in found if what.startswith("count ")], found


def test_a_count_computed_with_a_lambda_is_refused(tmp_path: Path) -> None:
    """The rule used to refuse any angle bracket in the interpolation, `=>` included.

    So a count summed with `reduce` or measured with `filter` escaped it, and the one
    at the knowledge-base `vectors` node had to be found by hand (#246). What
    distinguishes a count from a conditional is the *element* - `<span`, `</`, `/>` -
    and a lambda holds none of those.
    """
    source = "<span>{documents.reduce((sum, d) => sum + d.chunk_count, 0)} vectors</span>\n"
    found = _offences(tmp_path, source)
    assert [what for _, what in found if what.startswith("count ")], found
