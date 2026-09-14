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
    assert guard.update([docs / "install.pl.md"]) == 0
    assert guard.recorded_fingerprint(docs / "install.pl.md") == guard.fingerprint(source)
    assert guard.stale() == []


def test_update_adds_front_matter_to_a_translation_that_has_none(docs: Path) -> None:
    source = _english(docs, "install.md")
    (docs / "install.pl.md").write_text("# Tytuł\n\nTekst.\n", encoding="utf-8")
    guard.update([docs / "install.pl.md"])
    translated = docs / "install.pl.md"
    assert guard.recorded_fingerprint(translated) == guard.fingerprint(source)
    assert translated.read_text(encoding="utf-8").endswith("# Tytuł\n\nTekst.\n")


def test_update_leaves_a_translation_it_was_not_given(docs: Path) -> None:
    """The failure the whole design exists to prevent, reached through `--update`.

    Two English pages change, the translator retranslates one and records it. An
    update that stamped everything stale would mark the other current too - it
    keeps its old text, the reader's staleness notice disappears, and the gate
    never mentions it again. So it is stamped only if it was named.
    """
    first, second = _english(docs, "a.md"), _english(docs, "b.md")
    _translated(docs, "a.pl.md", guard.fingerprint(first))
    _translated(docs, "b.pl.md", guard.fingerprint(second))
    for page in (first, second):
        page.write_text("# Title\n\nText, changed.\n", encoding="utf-8")

    guard.update([docs / "a.pl.md"])

    assert guard.stale() == [("b.md", "pl")]


def test_update_refuses_a_path_that_is_not_a_translation(docs: Path) -> None:
    _english(docs, "install.md")
    assert guard.update([docs / "install.md"]) == 1


def test_update_refuses_a_translation_of_a_page_that_is_not_there(docs: Path) -> None:
    _translated(docs, "gone.pl.md", "0" * 12)
    assert guard.update([docs / "gone.pl.md"]) == 1


def test_a_fingerprint_of_only_digits_survives_yaml(docs: Path) -> None:
    """A quoted fingerprint, because roughly one in 281 is all decimal digits.

    Unquoted, YAML hands `page.meta` an integer while `fingerprint()` returns a
    string, so the build hook stamps "this translation is outdated" on a page
    that is current - on the site only, while this guard, which reads the raw
    text, says it is fine.
    """
    yaml = pytest.importorskip("yaml")
    source = _english(docs, "install.md")
    (docs / "install.pl.md").write_text("# Tytuł\n", encoding="utf-8")
    guard.record_fingerprint(docs / "install.pl.md", "123456789012")

    front_matter = (docs / "install.pl.md").read_text(encoding="utf-8").split("---")[1]
    assert yaml.safe_load(front_matter)["source_sha"] == "123456789012"
    assert guard.recorded_fingerprint(docs / "install.pl.md") == "123456789012"

    guard.update([docs / "install.pl.md"])
    assert guard.recorded_fingerprint(docs / "install.pl.md") == guard.fingerprint(source)


def test_an_unquoted_fingerprint_is_still_read(docs: Path) -> None:
    """Quoting is new; a file written before it, or by hand, still has to work."""
    source = _english(docs, "install.md")
    (docs / "install.pl.md").write_text(
        f"---\nsource_sha: {guard.fingerprint(source)}\n---\n\n# Tytuł\n", encoding="utf-8"
    )
    assert guard.stale() == []


def test_the_fingerprint_does_not_depend_on_the_checkouts_line_endings(docs: Path) -> None:
    """Git's `core.autocrlf` writes CRLF on Windows, and the tracked bytes are LF.

    Hashing the bytes on disk would report every translation on the branch stale
    there, and `--update` would record hashes that go wrong again as soon as Git
    normalizes the files back for the commit.
    """
    text = "# Title\n\nOne line.\nAnother.\n"
    unix, windows = docs / "a.md", docs / "b.md"
    unix.write_bytes(text.encode("utf-8"))
    windows.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    assert guard.fingerprint(unix) == guard.fingerprint(windows)


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

    guard.update([translated])

    text = translated.read_text(encoding="utf-8")
    assert text.startswith(f"<!-- source_sha: {guard.fingerprint(source)} -->")
    assert "---" not in text, "front matter would render as a table at the top of the file"
    assert guard.stale() == []


def test_where_the_fingerprint_goes_does_not_depend_on_how_the_path_was_typed(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative path names the same file as an absolute one, and must be answered so.

    `--update README.pl.md` typed at a shell gives a path whose parent is `.`; the
    same file reached through `root_pages()` is absolute. Deciding on the parent
    without resolving it first put front matter in one and a comment in the other,
    so the file ended up carrying two fingerprints that disagreed - and the front
    matter renders as a table above the project's name, which is the thing the
    comment exists to avoid.
    """
    _readme(repository, _README)
    translated = repository / "README.pl.md"
    translated.write_text("# Projekt\n", encoding="utf-8")
    monkeypatch.chdir(repository)

    guard.update([Path("README.pl.md")])

    text = translated.read_text(encoding="utf-8")
    assert text.startswith("<!-- source_sha:")
    assert not text.startswith("---")
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


def _linking_readme(repository: Path) -> Path:
    """An English README that links out to a page the site translates."""
    (repository / "docs" / "install.md").write_text("# Install\n", encoding="utf-8")
    (repository / "docs" / "install.pl.md").write_text("# Instalacja\n", encoding="utf-8")
    return _readme(repository, "# Project\n\nSee [install](docs/install.md).\n\n## What it does\n")


def test_a_root_translation_linking_to_english_is_reported(repository: Path) -> None:
    """The first thing a reader meets after choosing a language.

    Pick Polski, follow the documentation link, and land back in English - which
    is the one thing picking a language was meant to avoid. Nothing else sees it:
    the link resolves, the page exists, and the section shape is untouched.
    """
    _linking_readme(repository)
    (repository / "README.pl.md").write_text(
        "# Projekt\n\nZobacz [instalację](docs/install.md).\n\n## Co robi\n", encoding="utf-8"
    )
    assert guard.restructured() == []
    assert guard.relinked() == [
        ("README.md", "pl", "a link to 'docs/install.md' where it owes one to 'docs/install.pl.md'")
    ]


def test_a_root_translation_linking_to_its_own_language_is_not(repository: Path) -> None:
    _linking_readme(repository)
    (repository / "README.pl.md").write_text(
        "# Projekt\n\nZobacz [instalację](docs/install.pl.md).\n\n## Co robi\n", encoding="utf-8"
    )
    assert guard.relinked() == []


def test_a_link_to_a_page_with_no_translation_stays_english(repository: Path) -> None:
    """`docs/ROADMAP.md` is not published and is owed no translation.

    Localizing every target blindly would point this one at a file nobody wrote.
    """
    (repository / "docs" / "ROADMAP.md").write_text("# Roadmap\n", encoding="utf-8")
    _readme(repository, "# Project\n\nSee [the roadmap](docs/ROADMAP.md).\n\n## What it does\n")
    (repository / "README.pl.md").write_text(
        "# Projekt\n\nZobacz [plan](docs/ROADMAP.md).\n\n## Co robi\n", encoding="utf-8"
    )
    assert guard.relinked() == []


def test_the_language_bar_is_not_asked_to_stay_in_one_language(repository: Path) -> None:
    """The one construct that points at other languages on purpose."""
    _readme(repository, "# Project\n\n[Polski](README.pl.md)\n\n## What it does\n")
    (repository / "README.pl.md").write_text(
        "# Projekt\n\n[English](README.md)\n\n## Co robi\n", encoding="utf-8"
    )
    assert guard.relinked() == []


def test_a_root_translation_that_drops_a_link_is_reported(repository: Path) -> None:
    _linking_readme(repository)
    (repository / "README.pl.md").write_text(
        "# Projekt\n\nTekst.\n\n## Co robi\n", encoding="utf-8"
    )
    assert guard.relinked() == [("README.md", "pl", "0 links against 1 in English")]


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
