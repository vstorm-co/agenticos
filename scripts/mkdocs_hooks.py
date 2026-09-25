"""Build-time fixups the site needs and no MkDocs plugin provides.

Two jobs. The first is telling a reader when the page in front of them is not
the translation its URL and its navigation imply - `fallback_to_default` serves
the English page under `/de/...` when nobody has translated it, and a page whose
English source moved on after it was translated looks exactly like a current one.
Both get an admonition in the reader's own language saying which they are
reading; `scripts/docs_i18n.py` defines what "current" means.

The second is the release-notes page, which shows `CHANGELOG.md` from the
repository root rather than keeping a second copy of it that drifts. Two things
stop that from being a `pymdownx.snippets` include:

- The changelog's internal links are written for GitHub -
  `[the spec reference](docs/reference/spec.md)`. Read from a page that already
  lives inside `docs/`, each of those resolves to `docs/docs/...`, which
  `mkdocs build --strict` fails on.
- A snippet is expanded by a markdown extension, which runs *after* every hook,
  so nothing in this file could reach the included text to fix it.

So the page carries a marker and this hook substitutes the changelog into it,
rewriting the links on the way through. The file stays correct on GitHub and the
page stays correct on the site.

The third is what a search engine or a link preview reads from a page's head.
Material writes the title, the description, the canonical URL and the `hreflang`
alternates, and nothing a social card or a rich result needs. So a page may set
`seo_title` for the `<title>` a search result shows, every page gets Open Graph
and Twitter tags, and a page with a "Frequently asked questions" section gets
`FAQPage` structured data read from that section's own headings - written once,
in the Markdown a reader sees, rather than a second copy in front matter that
drifts from it.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# MkDocs loads a hook straight from its path, without putting that path on
# `sys.path`, so a plain `import docs_i18n` fails however the two files sit
# beside each other.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from docs_i18n import DEFAULT_LOCALE, FINGERPRINT_KEY, english_source, fingerprint

if TYPE_CHECKING:
    from mkdocs.config.defaults import MkDocsConfig
    from mkdocs.structure.files import Files
    from mkdocs.structure.pages import Page

RELEASE_NOTES = "release-notes.md"
LLMS_TXT = "llms.txt"
CHANGELOG_MARKER = "<!-- changelog -->"
SEO_TITLE_KEY = "seo_title"
SOCIAL_IMAGE = "assets/social-preview.png"
# The id every locale's FAQ heading carries: translations pin English anchors, so
# `{ #frequently-asked-questions }` is the one marker the Polish page shares too.
FAQ_SECTION_ID = "frequently-asked-questions"
OG_LOCALES = {"en": "en_US", "pl": "pl_PL", "de": "de_DE", "es": "es_ES"}

_CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
_DOCS_LINK = re.compile(r"\]\(docs/(?=[\w./#-]+\))")
_LEADING_HEADING = re.compile(r"\A#\s.*?\n", re.DOTALL)
_TITLE = re.compile(r"<title>.*?</title>", re.DOTALL)
_HEADERLINK = re.compile(r'<a class="headerlink"[^>]*>.*?</a>', re.DOTALL)
_BLOCK_END = re.compile(r"</(?:p|li|td|th|pre|div)>|<br\s*/?>")
_TAG = re.compile(r"<[^>]+>")
_FAQ_QUESTION = re.compile(r'<h3 id="[^"]*">(.*?)</h3>', re.DOTALL)

# One admonition per locale rather than one English sentence for everybody: the
# reader this is addressed to is the one who chose a language and is now being
# handed something else, so it has to be readable to them. The language switcher
# in the header is two inches away, which is why neither notice links anywhere.
UNTRANSLATED = {
    "pl": (
        "Ta strona nie została jeszcze przetłumaczona",
        "Czytasz angielski oryginał. Tłumaczenie tej strony jeszcze nie powstało.",
    ),
    "de": (
        "Diese Seite ist noch nicht übersetzt",
        "Sie lesen das englische Original. Eine Übersetzung dieser Seite gibt es noch nicht.",
    ),
    "es": (
        "Esta página todavía no está traducida",
        "Estás leyendo el original en inglés. Aún no existe una traducción de esta página.",
    ),
}

OUT_OF_DATE = {
    "pl": (
        "To tłumaczenie jest nieaktualne",
        "Angielski oryginał zmienił się od czasu powstania tego tłumaczenia, więc część treści może już nie opisywać obecnego zachowania. Wersja angielska jest rozstrzygająca.",
    ),
    "de": (
        "Diese Übersetzung ist veraltet",
        "Das englische Original hat sich seit dieser Übersetzung geändert, daher beschreiben Teile davon möglicherweise nicht mehr das aktuelle Verhalten. Maßgeblich ist die englische Fassung.",
    ),
    "es": (
        "Esta traducción está desactualizada",
        "El original en inglés ha cambiado desde que se hizo esta traducción, así que algunas partes pueden no describir el comportamiento actual. La versión en inglés es la que manda.",
    ),
}


def _changelog_body() -> str:
    """The changelog from its first release heading, with site-relative links.

    The file opens on a title and a preamble that the page states in its own
    words; keeping both would print them twice.
    """
    text = _CHANGELOG.read_text(encoding="utf-8")
    start = text.index("\n## ")
    return _DOCS_LINK.sub("](", text[start + 1 :]).strip()


def _admonition(notice: tuple[str, str]) -> str:
    title, body = notice
    return f'!!! warning "{title}"\n\n    {body}\n\n'


def _translation_notice(page: Page, locale: str) -> str | None:
    """The notice this page owes its reader, if it owes one.

    `page.file.locale` is the language of the file actually being rendered, so
    it disagreeing with the language being built *is* the fallback: English text
    about to be served under a localized URL.
    """
    if locale == DEFAULT_LOCALE:
        return None
    if page.file.locale != locale:
        return _admonition(UNTRANSLATED[locale])
    source = english_source(Path(page.file.abs_src_path))
    # `str()` because YAML reads an all-digit fingerprint as an integer, and about
    # one fingerprint in 281 is all digits. `record_fingerprint` quotes what it
    # writes, so this only catches a value somebody typed in by hand - but the
    # failure it prevents is a current page telling its reader it is out of date.
    if str(page.meta.get(FINGERPRINT_KEY)) != fingerprint(source):
        return _admonition(OUT_OF_DATE[locale])
    return None


def on_page_markdown(
    markdown: str, *, page: Page, config: MkDocsConfig, files: Files
) -> str | None:
    """Mark an untranslated or outdated page, and fill in the release notes."""
    if english_source(Path(page.file.src_uri)).as_posix() == RELEASE_NOTES:
        markdown = markdown.replace(CHANGELOG_MARKER, _changelog_body())
    notice = _translation_notice(page, config.theme["language"])
    if notice is None:
        return markdown
    heading = _LEADING_HEADING.match(markdown)
    if heading is None:
        return notice + markdown
    return f"{heading.group()}\n{notice}{markdown[heading.end() :]}"


def _plain_text(fragment: str) -> str:
    """Rendered HTML as the sentence a reader sees: no tags, no pilcrow, one space."""
    text = _BLOCK_END.sub(" ", _HEADERLINK.sub("", fragment))
    return " ".join(html.unescape(_TAG.sub("", text)).split())


def faq_entries(output: str) -> list[tuple[str, str]]:
    """Question and answer pairs from a page's FAQ section, in page order.

    The section runs from its `h2` to the next `h2` or the end of the article, and
    each `h3` inside it is a question whose answer is everything up to the next.
    A question with no answer text is left out rather than published empty.
    """
    start = output.find(f'<h2 id="{FAQ_SECTION_ID}">')
    if start == -1:
        return []
    body = output.index("</h2>", start) + len("</h2>")
    ends = [i for i in (output.find("<h2", body), output.find("</article>", body)) if i != -1]
    section = output[body : min(ends)] if ends else output[body:]
    parts = _FAQ_QUESTION.split(section)
    pairs = (
        (_plain_text(q), _plain_text(a)) for q, a in zip(parts[1::2], parts[2::2], strict=True)
    )
    return [(question, answer) for question, answer in pairs if question and answer]


def _json_ld(data: dict[str, object]) -> str:
    # `</` would close the script element early, whatever the JSON around it says.
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/ld+json">{payload}</script>'


def _site_root(config: MkDocsConfig) -> str:
    """The English site's root URL, which is where the shared assets are served.

    A localized build answers `site_url` with its own prefix - `.../pl/` - and the
    assets are not copied under it, so an image URL built from that would 404.
    """
    root = (config.site_url or "").rstrip("/")
    locale = config.theme["language"]
    if locale != DEFAULT_LOCALE and root.endswith(f"/{locale}"):
        root = root[: -len(locale) - 1]
    return f"{root}/"


def head_tags(output: str, *, page: Page, config: MkDocsConfig) -> str:
    """The social-card and structured-data tags this page adds to its `<head>`.

    A card's title is the `<title>` the page already renders, so a shared link and
    a search result name the page the same way.
    """
    rendered = _TITLE.search(output)
    title = _plain_text(rendered.group()) if rendered else config.site_name
    description = str(page.meta.get("description") or config.site_description or "")
    image = _site_root(config) + SOCIAL_IMAGE
    locale = config.theme["language"]
    properties = {
        "og:type": "website",
        "og:site_name": config.site_name,
        "og:title": title,
        "og:description": description,
        "og:url": page.canonical_url or "",
        "og:image": image,
        "og:locale": OG_LOCALES.get(locale, locale),
    }
    names = {
        "twitter:card": "summary_large_image",
        "twitter:title": title,
        "twitter:description": description,
        "twitter:image": image,
    }
    tags = [
        f'<meta property="{key}" content="{html.escape(value)}">'
        for key, value in properties.items()
        if value
    ]
    tags += [
        f'<meta name="{key}" content="{html.escape(value)}">'
        for key, value in names.items()
        if value
    ]
    faq = faq_entries(output)
    if faq:
        tags.append(
            _json_ld(
                {
                    "@context": "https://schema.org",
                    "@type": "FAQPage",
                    "inLanguage": locale,
                    "mainEntity": [
                        {
                            "@type": "Question",
                            "name": q,
                            "acceptedAnswer": {"@type": "Answer", "text": a},
                        }
                        for q, a in faq
                    ],
                }
            )
        )
    return "".join(tags)


def on_post_page(output: str, *, page: Page, config: MkDocsConfig) -> str:
    """Apply a page's `seo_title` and add its social and structured-data tags."""
    seo_title = page.meta.get(SEO_TITLE_KEY)
    if seo_title:
        output = _TITLE.sub(
            lambda _: f"<title>{html.escape(str(seo_title))}</title>", output, count=1
        )
    return output.replace("</head>", head_tags(output, page=page, config=config) + "</head>", 1)


def on_post_build(*, config: MkDocsConfig) -> None:
    """Copy `llms.txt` from the repository root into the built site.

    The file is how a language model is meant to discover what a project is, so
    it has to be served at the site root - and it is also the first thing
    somebody browsing the repository looks for, so it has to be at the
    repository root. Copying beats keeping two of them: the version that would
    drift is the one nobody edits, and it is the one the models read.

    `docs_dir` cannot reach outside itself, which is why this is a hook rather
    than a file in `docs/`.
    """
    source = Path(__file__).resolve().parent.parent / LLMS_TXT
    shutil.copyfile(source, Path(config.site_dir) / LLMS_TXT)
