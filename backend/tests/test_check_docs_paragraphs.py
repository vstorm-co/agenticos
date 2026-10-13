"""What the paragraph guard counts, and what it deliberately does not.

`scripts/check_docs_paragraphs.py` gates `make lint` on a rule the whole site was
swept to satisfy, so the interesting question is not "does it find a long
paragraph" but "does it find one *only* where a long paragraph is a defect".

A page is mostly not prose. Tables, fences, admonition bodies, bullet lists and
mermaid graphs all run past the limit legitimately and none of them is a wall of
text - a guard that counted them would be answered by exempting the page, which
is how a gate stops gating.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "check_docs_paragraphs.py"
_spec = importlib.util.spec_from_file_location("check_docs_paragraphs_under_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

LONG = " ".join(["word"] * (guard.MAX_WORDS + 1))
SHORT = " ".join(["word"] * (guard.MAX_WORDS - 1))


def _page(root: Path, relative: str, body: str) -> None:
    page = root / relative
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(body, encoding="utf-8")


@pytest.fixture
def docs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "docs"
    root.mkdir()
    monkeypatch.setattr(guard, "DOCS", root)
    return root


def test_a_long_prose_paragraph_is_reported(docs: Path) -> None:
    _page(docs, "page.md", f"# Title\n\n{LONG}\n")
    found = guard.offences()
    assert [words for _, words, _ in found] == [guard.MAX_WORDS + 1]


def test_a_short_paragraph_is_not(docs: Path) -> None:
    _page(docs, "page.md", f"# Title\n\n{SHORT}\n")
    assert guard.offences() == []


@pytest.mark.parametrize(
    "block",
    [
        f"| a | b |\n|---|---|\n| {LONG} | x |",
        f"```python\n{LONG}\n```",
        f'!!! warning "A title"\n\n    {LONG}',
        f"- {LONG}",
        f"* {LONG}",
        f"1. {LONG}",
        f"> {LONG}",
        f"### {LONG}",
        f"    {LONG}",
        f'=== "A tab"\n\n    {LONG}',
    ],
    ids=[
        "table",
        "fence",
        "admonition",
        "dash",
        "star",
        "ordered",
        "quote",
        "heading",
        "indent",
        "tab",
    ],
)
def test_what_is_not_prose_is_not_counted(docs: Path, block: str) -> None:
    """Each of these runs past the limit legitimately and none is a wall of text."""
    _page(docs, "page.md", f"# Title\n\n{block}\n")
    assert guard.offences() == []


@pytest.mark.parametrize("folder", sorted(guard.WORKING_NOTES))
def test_working_notes_are_exempt(docs: Path, folder: str) -> None:
    """`design/`, `plans/` and `audits/` are engineering notes, not site pages."""
    _page(docs, f"{folder}/note.md", f"# Note\n\n{LONG}\n")
    assert guard.offences() == []


def test_the_site_itself_passes() -> None:
    """The rule the repository actually holds itself to."""
    assert guard.offences() == []
