"""`lint_page`: what a published page gets told about itself, and what it is not told.

Every problem here is one a real model's page had (#1974): no doctype, a class the
kit never defined, a table built row by row with no head, icons with no icon
library, `AO.onData` on a kit that has none. A warning is only worth its tokens
when it fires on those and stays quiet on a page built as the guide says.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import artifact_lint
from app.services.artifact_lint import KIT_CLASSES, LATEST_KIT, class_vocabulary, lint_page

HEAD = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Open tickets</title>
<link rel="stylesheet" href="lib/agenticos-{kit}.css">
<script src="lib/lucide-1.46.0.min.js"></script>
<script src="lib/agenticos-{kit}.js"></script>
</head>"""


def _page(body: str, *, kit: int = 3, head: str | None = None) -> bytes:
    return (
        (head if head is not None else HEAD.format(kit=kit)) + f"<body>{body}</body></html>"
    ).encode()


GOOD_BODY = """<main class="ao-page">
<header class="ao-header"><div><h1>Open tickets</h1><p class="ao-subtitle">Seven.</p></div></header>
<div class="ao-table-wrap"><table class="ao-table">
<thead><tr><th>Title</th><th class="ao-num">Age</th></tr></thead>
<tbody><tr><td class="ao-strong">Printer</td><td class="ao-num">3</td></tr></tbody>
</table></div>
<p><i data-lucide="info"></i>From the queue.</p>
<div id="live"></div>
</main>
<script>agenticos.onData(function (data) { AO.records("#live", data.tickets); });</script>"""


def test_a_page_built_as_the_guide_says_is_not_warned() -> None:
    assert lint_page(_page(GOOD_BODY), bound=["tickets"]) == []


def test_a_script_closed_with_an_escaped_tag_is_told_first() -> None:
    """`<\\/script>` is an escape inside a JavaScript string, not a closing tag.

    A real agent ended its page that way, so the browser read the rest of the page
    as script, failed to parse it, and the live page drew nothing.
    """
    page = _page(GOOD_BODY).replace(b"</script>", b"<\\/script>")

    problems = lint_page(page)

    assert problems[0].startswith("A `<script>` is never closed")
    assert "`</script>`" in problems[0]


def test_a_page_with_no_doctype_or_viewport_is_told_both() -> None:
    head = '<html><head><link rel="stylesheet" href="lib/agenticos-3.css"></head>'
    problems = lint_page(_page("<main class='ao-page'></main>", head=head))
    assert len(problems) == 2
    assert "`<!doctype html>`" in problems[0]
    assert "viewport" in problems[1]


@pytest.mark.parametrize(
    "lead",
    [b"\xef\xbb\xbf", b"\n  ", b"<!-- built by an agent -->\n", b""],
    ids=["byte-order-mark", "whitespace", "comment", "nothing"],
)
def test_a_doctype_after_a_mark_whitespace_or_a_comment_still_counts(lead: bytes) -> None:
    problems = lint_page(lead + _page("<main class='ao-page'></main>"))
    assert not any("doctype" in problem for problem in problems)


def test_a_doctype_later_in_the_page_does_not_count() -> None:
    page = b"<p>x</p><!doctype html>" + _page("", head="")
    assert any("doctype" in problem for problem in lint_page(page))


def test_a_class_the_loaded_kit_never_defined_is_named() -> None:
    problems = lint_page(
        _page('<main class="ao-page ao-container"><p class="ao-text">x</p></main>')
    )
    assert problems == [
        "`lib/agenticos-3.css` defines no `ao-container`, `ao-text`, so they do nothing. Use "
        "the kit's own classes (the `artifact-pages` guide lists them) or style them in the "
        "page's `<style>`."
    ]


def test_a_class_only_a_newer_kit_has_says_to_load_that_kit() -> None:
    """The gpt-4.1 page reached for a header icon on version 2; version 3 has one."""
    problems = lint_page(
        _page('<main class="ao-page"><span class="ao-header-icon"></span></main>', kit=2)
    )
    assert problems == [
        "`lib/agenticos-2.css` has no `ao-header-icon`; `lib/agenticos-3.css` does, so load "
        "that instead."
    ]


def test_classes_used_with_no_kit_loaded_say_to_load_it() -> None:
    head = '<!doctype html><head><meta name="viewport" content="width=device-width"></head>'
    problems = lint_page(_page('<main class="ao-page"></main>', head=head))
    assert len(problems) == 1
    assert "loads no page kit stylesheet" in problems[0]
    assert 'href="lib/agenticos-3.css"' in problems[0]


def test_a_class_the_page_styles_itself_is_its_own_business() -> None:
    body = '<style>.ao-ticket-card { padding: 1rem; }</style><div class="ao-ticket-card"></div>'
    assert lint_page(_page(body)) == []


def test_classes_a_script_names_are_checked_but_custom_properties_and_attributes_are_not() -> None:
    body = """<div data-ao-tabs></div><script>
    el.className = "ao-card ao-wizard";
    badge.className = "ao-badge-" + tone;
    AO.color("--ao-series-3");
    </script>"""
    problems = lint_page(_page(body))
    assert len(problems) == 1
    assert "`ao-wizard`" in problems[0]
    assert "ao-series-3" not in problems[0]
    assert "ao-tabs" not in problems[0]


def test_a_long_list_of_unknown_classes_is_cut() -> None:
    names = " ".join(f"ao-made-up-{n}" for n in range(12))
    (problem,) = lint_page(_page(f'<div class="{names}"></div>'))
    assert "and 4 more" in problem
    assert problem.count("`ao-made-up-") == 8


def test_a_table_built_row_by_row_with_no_head_is_told_both_ways() -> None:
    """The page that started this: rows appended straight to an unstyled table."""
    body = """<table id="t"></table><script>
    const tr = document.createElement("tr"); document.getElementById("t").append(tr);
    </script>"""
    problems = lint_page(_page(body))
    assert len(problems) == 2
    assert "no `<thead>`" in problems[0]
    assert "no `ao-table` class" in problems[1]


def test_a_table_a_script_builds_with_a_head_and_the_class_is_fine() -> None:
    body = """<div class="ao-table-wrap"><table class="ao-table" id="t"></table></div><script>
    const table = document.getElementById("t"); table.createTHead(); table.createTBody();
    </script>"""
    assert lint_page(_page(body)) == []


def test_a_table_created_in_script_without_a_head_is_warned() -> None:
    body = '<script>const t = document.createElement("table"); t.className = "ao-table";</script>'
    problems = lint_page(_page(body))
    assert len(problems) == 1
    assert "no `<thead>`" in problems[0]


def test_icons_without_the_icon_library_are_warned() -> None:
    head = HEAD.format(kit=3).replace('<script src="lib/lucide-1.46.0.min.js"></script>', "")
    problems = lint_page(_page('<i data-lucide="star"></i>', head=head))
    assert problems == [
        f"It uses `data-lucide` icons but does not load `lib/{artifact_lint.LUCIDE_FILE}`, so "
        "they stay blank. Load it before the kit's script."
    ]


def test_icons_a_script_adds_count_as_icons_too() -> None:
    head = HEAD.format(kit=3).replace('<script src="lib/lucide-1.46.0.min.js"></script>', "")
    body = "<script>cell.innerHTML = '<i data-lucide=\"check\"></i>';</script>"
    assert len(lint_page(_page(body, head=head))) == 1


@pytest.mark.parametrize(
    ("script", "named"),
    [
        ("AO.onData(render);", "`AO.onData`"),
        ('AO.records("#t", data.t);', "`AO.records`"),
        ("AO.onData(function (d) { AO.records('#t', d.t); });", "`AO.onData` and `AO.records`"),
        ('AO.run("Refresh", {});', "`AO.run`"),
        ("AO.onRun(show); AO.run('x');", "`AO.onRun` and `AO.run`"),
    ],
)
def test_a_version_3_call_on_a_version_2_page_says_how_to_fix_it(script: str, named: str) -> None:
    problems = lint_page(_page(f"<script>{script}</script>", kit=2))
    assert any(
        problem.startswith(f"It calls {named}, which only `lib/agenticos-3.js` has")
        for problem in problems
    )


def test_a_version_2_page_calling_run_is_pointed_at_the_platform_call() -> None:
    problems = lint_page(_page('<script>AO.run("Refresh");</script>', kit=2))
    assert any("or call `agenticos.run` directly." in problem for problem in problems)


def test_ao_on_data_on_version_3_asks_for_the_data() -> None:
    assert lint_page(_page("<script>AO.onData(render);</script>"), bound=["tickets"]) == []


@pytest.mark.parametrize(
    "script",
    [
        "window.AO.chart(c, {});",
        "",
        # `AO.onData` on version 2 throws, so it never asks: both problems are said.
        "AO.onData(render);",
    ],
)
def test_a_bound_page_that_never_asks_for_its_data_is_warned(script: str) -> None:
    problems = lint_page(_page(f"<script>{script}</script>", kit=2), bound=["tickets", "people"])
    assert problems[-1].startswith(
        "It is bound to people, tickets but its script never calls `agenticos.onData`"
    )


@pytest.mark.parametrize(
    "script", ["agenticos.onData(render);", "window.agenticos.data.then(render);"]
)
def test_a_bound_page_that_asks_the_bridge_is_not_warned(script: str) -> None:
    assert lint_page(_page(f"<script>{script}</script>", kit=2), bound=["tickets"]) == []


def test_an_unbound_page_is_not_asked_for_data() -> None:
    assert lint_page(_page("<p>x</p>")) == []


def test_bytes_that_are_not_utf_8_are_read_rather_than_refused() -> None:
    assert lint_page(_page("<p>x</p>") + b"<p>\xff\xfe</p>") == []


class TestTheVocabulary:
    def test_it_is_read_from_every_served_kit_stylesheet(self) -> None:
        assert sorted(KIT_CLASSES) == [1, 2, 3]
        assert LATEST_KIT == 3
        assert {"ao-table", "ao-loading", "ao-header-actions"} <= KIT_CLASSES[3]
        assert "ao-loading" not in KIT_CLASSES[2]

    def test_only_a_versioned_kit_stylesheet_is_a_kit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "agenticos-4.css").write_text(".ao-new { }", encoding="utf-8")
        (tmp_path / "agenticos-print.css").write_text(".ao-print { }", encoding="utf-8")
        monkeypatch.setattr(artifact_lint, "_LIBRARY_ROOT", tmp_path)
        assert artifact_lint._kits() == {4: frozenset({"ao-new"})}

    def test_a_class_named_only_in_a_comment_is_not_one(self) -> None:
        css = "/* .ao-ghost is gone */ .ao-card > .ao-table-wrap, .ao-x:hover { color: red }"
        assert class_vocabulary(css) == {"ao-card", "ao-table-wrap", "ao-x"}
