"""What the build hook adds to a page's head for search engines and link previews.

Material renders the title, the description and the canonical URL, and nothing a
social card or a rich result reads. The hook adds those, and reads a page's FAQ
structured data out of the page's own rendered FAQ section - so the risk worth
testing is the extraction: a pilcrow in a question, an answer that swallows the
next section, a link that leaves a stray space before a full stop, or a `</` that
closes the script element early.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = REPO_ROOT / "scripts"

sys.path.insert(0, str(_SCRIPTS))
_spec = importlib.util.spec_from_file_location(
    "mkdocs_hooks_seo_under_test", _SCRIPTS / "mkdocs_hooks.py"
)
assert _spec is not None and _spec.loader is not None
hooks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hooks)


@dataclass
class _Page:
    canonical_url: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Config:
    site_url: str = "https://example.org/docs/"
    site_name: str = "AgenticOS"
    site_description: str = "The site description."
    theme: dict[str, str] = field(default_factory=lambda: {"language": "en"})


def _heading(level: int, anchor: str, text: str) -> str:
    link = f'<a class="headerlink" href="#{anchor}" title="Permanent link">&para;</a>'
    return f'<h{level} id="{anchor}">{text}{link}</h{level}>'


FAQ_PAGE = (
    "<html><head><title>AgenticOS vs Dify - AgenticOS</title></head><body>"
    '<article class="md-content__inner md-typeset">'
    + _heading(2, "at-a-glance", "At a glance")
    + "<p>Not a question.</p>"
    + _heading(2, "frequently-asked-questions", "Frequently asked questions")
    + _heading(3, "is-it-open-source", "Is it open source?")
    + '<p>Yes. See the <a href="../licenses/">licences</a>.</p>'
    + _heading(3, "what-does-it-cost", "What does it cost &amp; who pays?")
    + "<p>No seat fee.</p><ul><li>Models</li><li>Infrastructure</li></ul>"
    + _heading(3, "empty", "A question nobody answered?")
    + _heading(2, "sources", "Sources")
    + "<p>Vendor pages.</p>"
    "</article></body></html>"
)


def _structured(output: str) -> dict[str, Any]:
    found = re.findall(r'<script type="application/ld\+json">(.*?)</script>', output)
    assert len(found) == 1
    return json.loads(found[0])


def test_faq_questions_and_answers_read_as_the_reader_sees_them() -> None:
    assert hooks.faq_entries(FAQ_PAGE) == [
        ("Is it open source?", "Yes. See the licences."),
        ("What does it cost & who pays?", "No seat fee. Models Infrastructure"),
    ]


def test_the_faq_section_stops_at_the_next_section() -> None:
    answers = " ".join(answer for _, answer in hooks.faq_entries(FAQ_PAGE))
    assert "Vendor pages" not in answers


def test_a_page_without_an_faq_section_has_no_structured_data() -> None:
    page = _Page(canonical_url="https://example.org/docs/install/")
    output = "<html><head><title>Install - AgenticOS</title></head><body><article><p>Text.</p></article></body></html>"
    rendered = hooks.on_post_page(output, page=page, config=_Config())
    assert "application/ld+json" not in rendered
    assert '<meta property="og:title" content="Install - AgenticOS">' in rendered


def test_an_seo_title_replaces_the_rendered_title_and_names_the_card() -> None:
    page = _Page(
        canonical_url="https://example.org/docs/about/dify/",
        meta={
            "seo_title": 'AgenticOS vs Dify: "open" & multi-tenant',
            "description": "Compare them.",
        },
    )
    rendered = hooks.on_post_page(FAQ_PAGE, page=page, config=_Config())

    assert "<title>AgenticOS vs Dify: &quot;open&quot; &amp; multi-tenant</title>" in rendered
    assert "AgenticOS vs Dify - AgenticOS" not in rendered
    assert (
        '<meta property="og:title" content="AgenticOS vs Dify: &quot;open&quot; &amp; multi-tenant">'
        in rendered
    )
    assert '<meta property="og:description" content="Compare them.">' in rendered
    assert '<meta property="og:url" content="https://example.org/docs/about/dify/">' in rendered
    assert _structured(rendered)["@type"] == "FAQPage"
    assert len(_structured(rendered)["mainEntity"]) == 2


def test_a_page_with_no_description_falls_back_to_the_site_description() -> None:
    page = _Page(canonical_url="https://example.org/docs/install/")
    rendered = hooks.on_post_page(FAQ_PAGE, page=page, config=_Config())
    assert '<meta name="twitter:description" content="The site description.">' in rendered


def test_a_localized_page_points_its_card_at_the_shared_image_at_the_site_root() -> None:
    """A localized build's `site_url` carries its prefix; the assets are not copied under it."""
    config = _Config(site_url="https://example.org/docs/pl/", theme={"language": "pl"})
    page = _Page(canonical_url="https://example.org/docs/pl/about/dify/")
    rendered = hooks.on_post_page(FAQ_PAGE, page=page, config=config)

    assert (
        '<meta property="og:image" content="https://example.org/docs/assets/social-preview.png">'
        in rendered
    )
    assert '<meta property="og:locale" content="pl_PL">' in rendered
    assert _structured(rendered)["inLanguage"] == "pl"


def test_an_answer_cannot_close_the_structured_data_script_early() -> None:
    output = FAQ_PAGE.replace("No seat fee.", "Write &lt;/script&gt; literally.")
    page = _Page(canonical_url="https://example.org/docs/about/dify/")
    rendered = hooks.on_post_page(output, page=page, config=_Config())

    data = _structured(rendered)
    assert (
        data["mainEntity"][1]["acceptedAnswer"]["text"]
        == "Write </script> literally. Models Infrastructure"
    )


def test_a_card_field_with_no_value_is_left_out() -> None:
    config = _Config(site_description="")
    page = _Page(canonical_url="")
    output = "<html><head><title>Install</title></head><body></body></html>"
    rendered = hooks.on_post_page(output, page=page, config=config)
    assert 'property="og:url"' not in rendered
    assert 'property="og:description"' not in rendered
