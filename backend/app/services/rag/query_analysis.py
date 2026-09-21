"""Optional query analysis and expansion, run before retrieval (#1649).

An opt-in, per-agent step that improves recall on short, underspecified or
vocabulary-mismatched queries. It produces one or more *alternative query
strings* and nothing else: it never touches the :class:`RetrievalScope` or the
:class:`RetrievalFilters`, so an expanded query is searched under exactly the
same server-trusted tenant scope and business filters as the original (FA-039).
Widening access through expansion is therefore structurally impossible - the
only thing expansion can change is what text is searched for, never where.

Three modes, off by default:

- `keywords` - algorithmic term extraction appended to the query, with no
  model call, strengthening the lexical/BM25 leg.
- `multi_query` - a model rewrites the query into a bounded set of variants;
  the originals and the variants are all retrieved and their results fused.
- `hyde` - a model writes a short hypothetical answer passage, and retrieval
  runs against *its* embedding instead of the bare query's.

The model-backed modes take a `generate` callback rather than a model name.
The callback is built from the run's own model (`ctx.model`), whose credential
was already resolved from the vault - a model named as a string here would be
looked up against process environment variables, which on this platform is
either nothing or somebody else's key. A caller with no model to run (a channel
searching directly) passes `None` and the step degrades to the plain query.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Literal

logger = logging.getLogger(__name__)

QueryAnalysisMode = Literal["off", "keywords", "multi_query", "hyde"]
"""Which analysis a binding chose.

Stored in published specs and exported into a client's git repository, so these
four strings are as permanent as the capability id. A mode that stops making
sense is deprecated in the documentation; the value keeps resolving.
"""

GenerateText = Callable[[str], Awaitable[str]]
"""Run one prompt through the run's model and return its text.

The single seam between this module and the agent's model plumbing: the whole
prompt is built here and passed in, so the callback is a plain metered model
call with nothing model-specific leaking into retrieval, and a test supplies a
fake one without a provider."""

# A small, self-contained stop list. Query analysis is not linguistics: the aim
# is only to drop the function words that carry no retrieval signal so the terms
# that remain strengthen the lexical leg. A heavier NLP dependency would be a new
# install for a list this size.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9'-]*")

# A model asked for one variant per line still tends to number or bullet them;
# strip the marker rather than let it pollute the search terms.
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")

# What multi_query and hyde are bounded to regardless of a misbehaving model, so
# a single expansion can never fan out without limit. `max_variants` bounds the
# count a binding asks for; this bounds the length of any one produced string,
# because a model told to write "one query per line" can answer with a paragraph.
_MAX_VARIANT_CHARS = 400
_MAX_HYDE_CHARS = 2000


def extract_keywords(query: str) -> list[str]:
    """The content terms of a query, lower-cased, in first-seen order.

    Stop words and one-character tokens are dropped, duplicates collapsed. The
    order is preserved rather than sorted so the reconstructed query reads in the
    caller's own emphasis. An all-stopword query yields an empty list, and the
    caller then searches the query unchanged rather than an empty one.
    """
    seen: set[str] = set()
    keywords: list[str] = []
    for token in _WORD_RE.findall(query.lower()):
        if len(token) < 2 or token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        keywords.append(token)
    return keywords


def _keyword_boosted(query: str) -> str:
    """The query with its own content terms appended, boosting them in BM25.

    BM25 tokenises by whitespace, so repeating the content terms raises their
    term frequency in the query and pulls documents that use that exact
    vocabulary up the lexical ranking - which is the whole of what `keywords`
    mode is for. A query that is all stop words is returned unchanged.
    """
    keywords = extract_keywords(query)
    if not keywords:
        return query
    return f"{query} {' '.join(keywords)}"


_MULTI_QUERY_PROMPT = (
    "You rewrite a search query into alternative phrasings that improve document "
    "retrieval. Write up to {n} alternative search queries for the query below, "
    "one per line, with no numbering, quotes or commentary. Each must keep the "
    "original intent while varying the vocabulary or the specificity.\n\n"
    "Query: {query}"
)

_HYDE_PROMPT = (
    "Write a short, factual passage of two to four sentences that would directly "
    "answer the question below, as if it were an excerpt from a relevant "
    "document. Do not add commentary, headings or a preamble - write only the "
    "passage.\n\n"
    "Question: {query}"
)


def _clean_variant(line: str) -> str:
    """One model line as a usable query: list marker stripped, surrounding quotes
    and whitespace removed, length bounded."""
    cleaned = _LIST_MARKER_RE.sub("", line).strip().strip("\"'").strip()
    return cleaned[:_MAX_VARIANT_CHARS]


async def multi_query_variants(
    query: str, *, generate: GenerateText, max_variants: int
) -> list[str]:
    """Alternative phrasings of the query, from the model, bounded and deduped.

    At most `max_variants` are returned. A variant equal to the original query
    (case-insensitively) or to an earlier variant is dropped, so the fan-out that
    follows searches distinct queries rather than paying for the same one twice.
    """
    raw = await generate(_MULTI_QUERY_PROMPT.format(n=max_variants, query=query))
    seen = {query.strip().lower()}
    variants: list[str] = []
    for line in raw.splitlines():
        variant = _clean_variant(line)
        key = variant.lower()
        if not variant or key in seen:
            continue
        seen.add(key)
        variants.append(variant)
        if len(variants) >= max_variants:
            break
    return variants


async def hypothetical_document(query: str, *, generate: GenerateText) -> str:
    """A short hypothetical answer passage for the query (HyDE).

    Retrieval embeds whatever string it is handed, so returning this passage in
    place of the query makes the dense leg match on the shape of an *answer*
    rather than a question - the recall win HyDE exists for. An empty generation
    falls back to the original query rather than embedding nothing.
    """
    passage = (await generate(_HYDE_PROMPT.format(query=query))).strip()
    return passage[:_MAX_HYDE_CHARS] if passage else query


async def plan_queries(
    query: str,
    *,
    mode: QueryAnalysisMode,
    max_variants: int,
    generate: GenerateText | None,
) -> list[str]:
    """The query strings to retrieve for, given the configured analysis mode.

    Always returns a non-empty list whose members are searched under the caller's
    unchanged scope and filters. `off` returns the query alone, so a fused
    retrieval over a one-element list is byte-for-byte the plain retrieval and
    enabling analysis is the only thing that changes behaviour.

    A model-backed mode with no `generate` (a surface with no model to run, or
    a model that cannot make a request-response call) degrades to the plain
    query, as does a generation that raises: expansion improves recall when it
    works and is never the reason a search fails.
    """
    if mode == "off":
        return [query]
    if mode == "keywords":
        return [_keyword_boosted(query)]
    if generate is None:
        return [query]
    try:
        if mode == "multi_query":
            variants = await multi_query_variants(
                query, generate=generate, max_variants=max_variants
            )
            return [query, *variants]
        return [await hypothetical_document(query, generate=generate)]
    except Exception:
        logger.warning(
            "Query analysis (%s) failed; falling back to the plain query", mode, exc_info=True
        )
        return [query]


__all__ = [
    "GenerateText",
    "QueryAnalysisMode",
    "extract_keywords",
    "hypothetical_document",
    "multi_query_variants",
    "plan_queries",
]
