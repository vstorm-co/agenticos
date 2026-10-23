"""What the docs glossary guard refuses, and what a reader does not read as prose.

`scripts/check_docs_glossary.py` gates `make lint` on the Polish and German pages
about the eval screens using the words the console uses. The interesting part is
where it does not look: code, link targets, anchors and an English console label
quoted in parentheses are what a correct page holds, so a guard that matched them
would be answered by rewriting what must not change.
"""

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "check_docs_glossary.py"
_spec = importlib.util.spec_from_file_location("check_docs_glossary_under_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

TERMS = {
    "mixed": {
        "pl": [
            {"key": "case", "pattern": "case'|\\bcase\\w*", "use": "przypadek"},
            {"key": "activity", "pattern": "\\bactivity\\b", "use": "Aktywność"},
            {"key": "szkic", "pattern": "\\bszkic\\w*", "use": "wersja robocza", "within": ["x"]},
        ],
        "de": [
            {
                "key": "kaputt",
                "pattern": "kaputt",
                "use": "verschlechtert",
                "within": ["x"],
                "docs": True,
            }
        ],
    },
    "docs": {
        "pages": ["evals"],
        "activityPages": {"pl": ["governance"]},
        "allow": {"pl": ["Eval judge"]},
    },
}


@pytest.fixture
def docs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "docs"
    root.mkdir()
    terms = tmp_path / "eval-terms.json"
    terms.write_text(json.dumps(TERMS), encoding="utf-8")
    monkeypatch.setattr(guard, "DOCS", root)
    monkeypatch.setattr(guard, "TERMS", terms)
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    for name in ("evals.pl.md", "evals.de.md", "governance.pl.md"):
        (root / name).write_text("Nic tu nie ma.\n", encoding="utf-8")
    return root


def _write(docs: Path, name: str, body: str) -> None:
    (docs / name).write_text(body, encoding="utf-8")


def test_a_mixed_form_in_prose_is_named_with_its_line_and_the_word_to_use(docs: Path) -> None:
    _write(docs, "evals.pl.md", "Wstęp.\n\nRun odpowiada na trzy case'y.\n")

    [(page, line, form, use)] = guard.offences()

    assert (page.name, line, form, use) == ("evals.pl.md", 3, "case'", "przypadek")


def test_what_a_reader_does_not_read_as_prose_is_left_alone(docs: Path) -> None:
    _write(
        docs,
        "evals.pl.md",
        "---\nsource_sha: case\n---\n"
        "Pole `case_count` i [przypadki](evals.md#case-list).\n"
        "## Lista { #cases }\n"
        "```\ncase = 1\n```\n"
        "Otwórz **Aktywność** (Activity) albo <span class='case'>x</span>.\n"
        "Sędzia **Eval judge** ocenia.\n",
    )

    assert guard.offences() == []


def test_a_page_checked_for_activity_alone_is_checked_for_nothing_else(docs: Path) -> None:
    _write(docs, "governance.pl.md", "Trzy case'y w Activity.\n")

    assert [(form, use) for _, _, form, use in guard.offences()] == [("Activity", "Aktywność")]


def test_a_word_wrong_in_one_sense_only_is_checked_where_it_says_so(docs: Path) -> None:
    _write(docs, "evals.pl.md", "Szkic czeka na akceptację.\n")
    _write(docs, "evals.de.md", "Macht Fälle kaputt.\n")

    assert [(page.name, form) for page, _, form, _ in guard.offences()] == [
        ("evals.de.md", "kaputt")
    ]


def test_the_verdict_is_said_and_the_exit_code_gates(docs: Path, capsys) -> None:
    assert guard.main() == 0
    assert "use the glossary's words" in capsys.readouterr().out

    _write(docs, "evals.pl.md", "Dwa case'y.\n")

    assert guard.main() == 1
    out = capsys.readouterr().out
    assert "docs/evals.pl.md:1: \"case'\" - write 'przypadek'" in out
    assert "translate.md" in out


def test_the_shared_terms_carry_what_the_guard_reads() -> None:
    terms = json.loads(guard.TERMS.read_text(encoding="utf-8"))

    assert {"pages", "activityPages", "allow"} <= set(terms["docs"])
    for entries in terms["mixed"].values():
        assert all({"key", "pattern", "use"} <= set(entry) for entry in entries)
