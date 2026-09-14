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
        monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(module, "LOCALES", ("pl",))
    # These tests are about the site's own tree; the repository's files have
    # their own fixture below, and leaving them in would make every count here
    # depend on how many of them the real repository happens to have.
    monkeypatch.setattr(docs_i18n, "ROOT_PAGES", ())
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


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository root of the test's own, holding one translatable root file.

    `REPO_ROOT` decides three separate things - which files `root_pages()`
    offers, whether a fingerprint is written as a comment or as front matter, and
    where `orphaned()` looks for a stranded translation - so both modules are
    patched, the same way the `docs` fixture patches `DOCS`.
    """
    root = tmp_path / "repo"
    root.mkdir()
    (root / "docs").mkdir()
    for module in (docs_i18n, guard):
        monkeypatch.setattr(module, "REPO_ROOT", root)
        monkeypatch.setattr(module, "DOCS", root / "docs")
        monkeypatch.setattr(module, "LOCALES", ("pl",))
    monkeypatch.setattr(docs_i18n, "ROOT_PAGES", ("README.md",))
    return root


def _readme(repository: Path, body: str) -> Path:
    page = repository / "README.md"
    page.write_text(body, encoding="utf-8")
    return page


_README = "# Project\n\n[jump](#what-it-does)\n\n## What it does\n\nText.\n"


def test_a_root_file_with_no_translation_is_reported(repository: Path) -> None:
    _readme(repository, _README)
    assert guard.missing() == [("README.md", "pl")]


def test_a_root_file_records_its_fingerprint_in_a_comment(repository: Path) -> None:
    source = _readme(repository, _README)
    translated = repository / "README.pl.md"
    translated.write_text("# Projekt\n\n[skocz](#co-robi)\n\n## Co robi\n\nTekst.\n", "utf-8")

    guard.update()

    text = translated.read_text(encoding="utf-8")
    assert text.startswith(f"<!-- source_sha: {guard.fingerprint(source)} -->")
    assert "---" not in text, "front matter would render as a table at the top of the file"
    assert guard.stale() == []


def test_a_root_translation_that_stops_halfway_is_reported(repository: Path) -> None:
    _readme(repository, _README)
    (repository / "README.pl.md").write_text("# Projekt\n\nTekst.\n", encoding="utf-8")
    assert guard.restructured() == [("README.md", "pl", "1 headings against 2 in English")]


def test_a_root_translation_keeping_the_english_sections_is_not(repository: Path) -> None:
    _readme(repository, _README)
    (repository / "README.pl.md").write_text(
        "# Projekt\n\n[skocz](#co-robi)\n\n## Co robi\n\nTekst.\n", encoding="utf-8"
    )
    assert guard.restructured() == []
    assert guard.dangling() == []


def test_a_root_translation_keeping_the_english_fragment_is_reported(repository: Path) -> None:
    """The failure this check exists for: the heading moved, the link did not.

    GitHub has no way to pin `#what-it-does` onto a Polish heading, so a
    translation that copies the English link across is left pointing at nothing -
    and GitHub answers it with the top of the page rather than an error.
    """
    _readme(repository, _README)
    (repository / "README.pl.md").write_text(
        "# Projekt\n\n[skocz](#what-it-does)\n\n## Co robi\n\nTekst.\n", encoding="utf-8"
    )
    assert guard.restructured() == []
    assert guard.dangling() == [("README.md", "pl", "what-it-does")]


def test_an_html_fragment_is_checked_too(repository: Path) -> None:
    _readme(repository, '# Project\n\n<a href="#what-it-does">jump</a>\n\n## What it does\n')
    (repository / "README.pl.md").write_text(
        '# Projekt\n\n<a href="#what-it-does">skocz</a>\n\n## Co robi\n', encoding="utf-8"
    )
    assert guard.dangling() == [("README.md", "pl", "what-it-does")]


def test_a_root_translation_of_a_deleted_file_is_orphaned(repository: Path) -> None:
    (repository / "GONE.pl.md").write_text("# Nieistotne\n", encoding="utf-8")
    assert guard.orphaned() == ["GONE.pl.md"]


def test_the_github_slug_answers_the_fragments_the_readme_links_to() -> None:
    """GitHub's rule, checked against the six fragments `README.md` already uses.

    The one that matters is `#-quick-start`: its heading opens on an emoji, and
    the space the emoji leaves behind becomes a leading hyphen. Derive the anchor
    the way the site does and you get `quick-start`, which is a link to nowhere.
    """
    readme = REPO_ROOT / "README.md"
    available = set(docs_i18n.github_anchors(readme))
    assert "-quick-start" in available
    assert set(docs_i18n.own_fragments(readme)) <= available


def test_the_slug_derivation_matches_the_renderer() -> None:
    """`_slugify` reproduces `toc`, and this is what keeps "reproduces" honest.

    The guard runs under the system interpreter and cannot import
    Python-Markdown, so it carries its own copy of the rule. A copy that has
    drifted fails in the one direction nothing else would catch: the gate
    compares two lists of anchors that the build never emits.

    Needs the renderer, which lives in the `docs` dependency group rather than
    `dev` - so this skips under `make test` and runs in CI's `docs` job, which
    installs that group and calls it by name. Skipping quietly in the job that
    cannot run it is the point; a test that skipped in *every* job would prove
    nothing while looking like it did.
    """
    markdown = pytest.importorskip("markdown")
    pytest.importorskip("pymdownx", reason="the docs group is not installed")

    def rendered(page: Path) -> list[str]:
        # `superfences` is not decoration here: without a fence extension a `#`
        # inside a code block is a heading, and the comparison would be against
        # a document the site never builds.
        parser = markdown.Markdown(
            extensions=["toc", "attr_list", "tables", "admonition", "pymdownx.superfences"]
        )
        parser.convert(page.read_text(encoding="utf-8"))

        def flatten(tokens: list[dict[str, object]]) -> list[str]:
            found: list[str] = []
            for token in tokens:
                found.append(str(token["id"]))
                found.extend(flatten(token["children"]))  # type: ignore[arg-type]
            return found

        return flatten(parser.toc_tokens)

    pages = docs_i18n.english_pages()
    assert pages, "the site has pages; a guard that checks none of them proves nothing"
    assert {page: docs_i18n.anchors(page) for page in pages} == {
        page: rendered(page) for page in pages
    }


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
