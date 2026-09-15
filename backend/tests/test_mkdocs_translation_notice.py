"""What the build hook tells a reader about the page they are looking at.

The guard in `check_docs_i18n.py` answers to a contributor and fails `make lint`.
This is the other half, and it answers to a reader: the site publishes four
languages from one tree with `fallback_to_default`, so a page nobody translated
still resolves under `/de/...` - in English, inside a German navigation, and
indistinguishable from a translated one unless something says so.

The interesting case is the one that only shows up on the rendered site. The
guard reads the fingerprint out of the raw text; the hook reads it out of
`page.meta`, which has been through a YAML parser on the way. A fingerprint of
twelve hex characters is all decimal digits about once in 281, and unquoted YAML
turns that into an integer - so a current page tells its reader it is out of
date, in a locale nobody checked, while `make lint` stays green.

The hook only needs `page.file.locale`, `page.file.abs_src_path` and `page.meta`,
and it imports mkdocs solely under `TYPE_CHECKING`, so the stubs below are the
whole of the fixture.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = REPO_ROOT / "scripts"

sys.path.insert(0, str(_SCRIPTS))
_spec = importlib.util.spec_from_file_location(
    "mkdocs_hooks_under_test", _SCRIPTS / "mkdocs_hooks.py"
)
assert _spec is not None and _spec.loader is not None
hooks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hooks)

import docs_i18n


@dataclass
class _File:
    locale: str
    abs_src_path: str


@dataclass
class _Page:
    file: _File
    meta: dict[str, Any] = field(default_factory=dict)


@pytest.fixture
def page(tmp_path: Path) -> Any:
    """A Polish page whose English source exists, with no fingerprint recorded yet."""
    (tmp_path / "install.md").write_text("# Install\n\nText.\n", encoding="utf-8")
    translated = tmp_path / "install.pl.md"
    translated.write_text("# Instalacja\n\nTekst.\n", encoding="utf-8")
    return _Page(file=_File(locale="pl", abs_src_path=str(translated)))


def _source_of(page: Any) -> Path:
    return hooks.english_source(Path(page.file.abs_src_path))


def test_a_current_translation_is_told_nothing(page: Any) -> None:
    page.meta = {"source_sha": hooks.fingerprint(_source_of(page))}
    assert hooks._translation_notice(page, "pl") is None


def test_a_translation_of_an_older_revision_is_marked(page: Any) -> None:
    page.meta = {"source_sha": "0" * 12}
    notice = hooks._translation_notice(page, "pl")
    assert notice is not None
    assert hooks.OUT_OF_DATE["pl"][0] in notice


def test_english_served_under_a_localized_url_is_marked(page: Any) -> None:
    """`page.file.locale` disagreeing with the locale being built *is* the fallback."""
    page.file.locale = "en"
    notice = hooks._translation_notice(page, "pl")
    assert notice is not None
    assert hooks.UNTRANSLATED["pl"][0] in notice


def test_the_english_build_is_never_marked(page: Any) -> None:
    assert hooks._translation_notice(page, hooks.DEFAULT_LOCALE) is None


def test_a_fingerprint_yaml_read_as_an_integer_does_not_mark_a_current_page(
    page: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect this comparison is written against.

    `page.meta` has been through a YAML parser, and an unquoted all-digit
    fingerprint arrives as an `int` while `fingerprint()` returns a `str`. Compared
    raw, they never match, and a reader is told a current page is out of date -
    on the rendered site only, in whichever locale drew the short straw.

    The source is made to hash to an all-digit value rather than waited for: one
    fingerprint in 281 is, which is often enough to happen and far too rare to
    reproduce on demand.
    """
    digits = "123456789012"
    assert len(digits) == docs_i18n.FINGERPRINT_LENGTH
    monkeypatch.setattr(hooks, "fingerprint", lambda _source: digits)
    page.meta = {"source_sha": int(digits)}

    assert hooks._translation_notice(page, "pl") is None
