"""The i18n guard reads copy in a prop, and only in the props it knows.

`scripts/check_i18n.py` reads a fixed list of attribute names - `READABLE_ATTRS` -
and a component taking copy through any other name is invisible to it. Two were,
and both shipped English into every locale (#362):

* `<Pager noun="skills">` at six call sites, whose message is `{matched} of
  {total} {noun}`. The sentence looked translated and rendered `3 of 40 skills`
  under `pl`, because English is the only language where a noun beside a number
  needs no agreement.
* `<Fact term="Chunking">` at four call sites on the ingestion panel, where every
  other `Fact` on the same panel already passed `t(...)`.

The list is the weakness of the mechanism rather than a bug in it - which is the
argument #395 records for replacing the whole script with a parser that reads a
prop's *value* instead of trusting its name. Until then, the list has to be
correct, and something has to check that it is.

**Which of these prove the fix:** the two refusal tests. Both pass only with
`noun` and `term` in `READABLE_ATTRS`, and both fail without them. The other two
are forward guards and each says so - they pass on `main` as well.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "check_i18n.py"
_spec = importlib.util.spec_from_file_location("check_i18n_attrs_under_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check_i18n = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_i18n)


def _offences(tmp_path: Path, source: str) -> list[tuple[int, str]]:
    sample = tmp_path / "sample.tsx"
    sample.write_text(source)
    return check_i18n.offences(sample)


def test_a_noun_passed_as_an_english_word_is_refused(tmp_path: Path) -> None:
    found = _offences(tmp_path, '<Pager page={0} noun="skills" onPage={setPage} />\n')
    assert [what for _, what in found if what.startswith("noun=")], found


def test_a_term_passed_as_an_english_word_is_refused(tmp_path: Path) -> None:
    found = _offences(tmp_path, '<Fact term="Chunking">{summary}</Fact>\n')
    assert [what for _, what in found if what.startswith("term=")], found


def test_the_same_props_read_from_the_catalog_pass(tmp_path: Path) -> None:
    """A forward guard, and it passes on `main` too - deliberately.

    `ATTR` only matches a double-quoted literal, so a braced value was invisible
    before `term` joined the list and is invisible after: this asserts nothing
    about the change that added it. It is here so that a future rule widened to
    read braced values - the obvious next step, and what #395's parser would do
    by default - cannot land while refusing the remedy this one demanded.
    """
    source = '<Fact term={t("chunking")}>{t("chunkingSummary", { size })}</Fact>\n'
    assert _offences(tmp_path, source) == []


def test_every_readable_attr_can_actually_be_matched(tmp_path: Path) -> None:
    """Every name in the tuple survives being compiled into `ATTR`.

    Not a drift check between two lists - there is only one, and `ATTR` is built
    from it on the same line, so they cannot disagree. What can go wrong is a
    name that the alternation cannot match once it is in there: a regex
    metacharacter interpolated raw, or a leading character `\\b` cannot anchor
    against. Either way the name reads as covered and matches nothing, and the
    failure is a green build.
    """
    for name in check_i18n.READABLE_ATTRS:
        found = _offences(tmp_path, f'<Thing {name}="Save changes" />\n')
        assert [what for _, what in found if what.startswith(f"{name}=")], name
