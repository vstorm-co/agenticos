"""The i18n guard refuses copy that leads with a word, `Rotate {name}`.

`scripts/check_i18n.py` had a hole exactly one word wide. `MIXED` counts the words
left after the interpolation is removed and fires at two, `COUNT` reads the single
word that *follows* one - and neither saw a single word in front of one. So
`Rotate {secret.name}`, `chunk {chunk.chunk}` and `Invited {date}` passed the gate
and rendered their English word verbatim under `pl`, which is the failure the guard
exists to prevent (#249).

The `LEAD` rule closes it. These are the regression tests that rule needs: a gate
whose failure mode is a green build needs something checking the checker.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "check_i18n.py"
_spec = importlib.util.spec_from_file_location("check_i18n_word_first_under_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check_i18n = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_i18n)


def _offences(tmp_path: Path, source: str) -> list[tuple[int, str]]:
    sample = tmp_path / "sample.tsx"
    sample.write_text(source)
    return check_i18n.offences(sample)


def test_a_word_before_an_interpolation_is_refused(tmp_path: Path) -> None:
    found = _offences(tmp_path, "<DialogTitle>Rotate {secret?.name}</DialogTitle>\n")
    assert found, found


def test_a_separator_in_front_of_the_word_does_not_hide_it(tmp_path: Path) -> None:
    """`· expires {date}` is the same string with punctuation in front of it.

    A dot separating one fragment from the next is markup, not a word, so the rule
    steps over it rather than counting it - otherwise every string inside a row of
    them would be exempt by virtue of the row.
    """
    found = _offences(tmp_path, "<> · expires {formatDate(inv.expires_at)}</>\n")
    assert found, found


def test_the_message_that_replaces_it_is_not_read_as_copy(tmp_path: Path) -> None:
    """The remedy has to pass, or the rule forbids its own fix.

    `t("rotateNamed", { name: … })` is a word followed by an interpolation to a
    regex that cannot see that the word is inside the call being made.
    """
    found = _offences(
        tmp_path, '<DialogTitle>{t("rotateNamed", { name: secret.name })}</DialogTitle>\n'
    )
    assert found == [], found


def test_a_word_before_a_guard_that_renders_an_element_is_not_copy(tmp_path: Path) -> None:
    """`{flag && <Badge />}` renders a component; the word belongs to the layout."""
    found = _offences(tmp_path, "<div>only {flag && <Badge />}</div>\n")
    assert found == [], found


def test_a_typescript_signature_is_still_not_read_as_a_text_node(tmp_path: Path) -> None:
    """The rules that need an interpolation now run on lines holding `=>`.

    That is what a `reduce`-built count needs, and it is only safe because a type
    annotation carries no `{expr}` next to a noun. `onTest: (() => Promise<void>)`
    is the shape that made the line-level skip necessary in the first place.
    """
    found = _offences(tmp_path, "  onTest: (() => Promise<void>) | null;\n")
    assert found == [], found
