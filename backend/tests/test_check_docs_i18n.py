"""What the translation guard counts, and what the locale list has to agree with.

`scripts/check_docs_i18n.py` gates `make lint` on a property that is otherwise
invisible: a page nobody translated still answers under a localized URL, in a
localized navigation, in English. So the interesting questions are whether the
guard sees a missing translation, whether it sees one that has fallen behind its
English source, and whether `--update` moves the fingerprint that decides.

The last test here is a parity check rather than a behaviour one. The guard's
locale list and the locales `mkdocs.yml` actually builds are two declarations of
the same fact, and the failure when they disagree is silent in the worst
direction: a locale the site publishes and the guard never asks about.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = REPO_ROOT / "scripts"

sys.path.insert(0, str(_SCRIPTS))
_spec = importlib.util.spec_from_file_location(
    "check_docs_i18n_under_test", _SCRIPTS / "check_docs_i18n.py"
)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

import docs_i18n


@pytest.fixture
def docs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A docs tree of the test's own, with one locale to keep assertions readable.

    Both modules are patched because the guard imports these names rather than
    the module: its own `DOCS` is what its functions read, and `docs_i18n`'s is
    what the helpers it calls read.
    """
    root = tmp_path / "docs"
    root.mkdir()
    for module in (docs_i18n, guard):
        monkeypatch.setattr(module, "DOCS", root)
        monkeypatch.setattr(module, "LOCALES", ("pl",))
    return root


def _english(docs: Path, name: str, body: str = "# Title\n\nText.\n") -> Path:
    page = docs / name
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(body, encoding="utf-8")
    return page


def _translated(docs: Path, name: str, source_sha: str) -> Path:
    page = docs / name
    page.write_text(f"---\nsource_sha: {source_sha}\n---\n\n# Tytuł\n\nTekst.\n", encoding="utf-8")
    return page


def test_a_page_with_no_translation_is_reported(docs: Path) -> None:
    _english(docs, "install.md")
    assert guard.missing() == [("install.md", "pl")]


def test_a_current_translation_is_not(docs: Path) -> None:
    source = _english(docs, "install.md")
    _translated(docs, "install.pl.md", guard.fingerprint(source))
    assert guard.missing() == []
    assert guard.stale() == []


def test_a_translation_of_an_older_revision_is_stale(docs: Path) -> None:
    source = _english(docs, "install.md")
    _translated(docs, "install.pl.md", guard.fingerprint(source))
    source.write_text("# Title\n\nText, and one more sentence.\n", encoding="utf-8")
    assert guard.stale() == [("install.md", "pl")]


def test_a_translation_with_no_recorded_revision_is_stale(docs: Path) -> None:
    _english(docs, "install.md")
    (docs / "install.pl.md").write_text("# Tytuł\n\nTekst.\n", encoding="utf-8")
    assert guard.stale() == [("install.md", "pl")]


def test_a_translation_of_a_deleted_page_is_orphaned(docs: Path) -> None:
    _translated(docs, "gone.pl.md", "0" * 12)
    assert guard.orphaned() == ["gone.pl.md"]


def test_update_records_the_current_revision(docs: Path) -> None:
    source = _english(docs, "install.md")
    _translated(docs, "install.pl.md", "0" * 12)
    assert guard.update() == 0
    assert guard.recorded_fingerprint(docs / "install.pl.md") == guard.fingerprint(source)
    assert guard.stale() == []


def test_update_adds_front_matter_to_a_translation_that_has_none(docs: Path) -> None:
    source = _english(docs, "install.md")
    (docs / "install.pl.md").write_text("# Tytuł\n\nTekst.\n", encoding="utf-8")
    guard.update()
    translated = docs / "install.pl.md"
    assert guard.recorded_fingerprint(translated) == guard.fingerprint(source)
    assert translated.read_text(encoding="utf-8").endswith("# Tytuł\n\nTekst.\n")


def test_working_notes_and_unpublished_pages_owe_no_translation(docs: Path) -> None:
    _english(docs, "plans/next-quarter.md")
    _english(docs, "ROADMAP.md")
    _english(docs, "about/design.md")
    assert guard.missing() == []


def test_the_guard_asks_about_every_locale_the_site_builds() -> None:
    config = yaml.load(
        (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,  # noqa: S506  constructs only str/list/dict; safe_load chokes on `!!python/name:`
    )
    i18n = next(
        plugin["i18n"]
        for plugin in config["plugins"]
        if isinstance(plugin, dict) and "i18n" in plugin
    )
    built = {language["locale"] for language in i18n["languages"]}
    assert built == {docs_i18n.DEFAULT_LOCALE, *docs_i18n.LOCALES}
