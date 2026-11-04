"""The question set: what a retrieval evaluation asks, and what counts as found.

A page is named by its *page key*: its path under `docs/` with the locale suffix
taken off, so `directory.md`, `directory.pl.md` and `directory.de.md` are all
`directory.md`. A retrieved chunk from any translation of an expected page is a
hit. Which translations are in reach is the corpus's business, not the item's:
a `cross_language` item names the one locale it is searched in, which is never
the language it is asked in, and that is what makes it cross-language.

The file is versioned. A change to what a field means bumps `version`, so a
result quoted against version 1 is never silently compared with one measured
against a different question set.
"""

import re
from pathlib import Path, PurePosixPath
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Category = Literal["factual", "negative", "cross_language"]
Locale = Literal["en", "pl", "de", "es"]

CATEGORIES: tuple[Category, ...] = ("factual", "negative", "cross_language")
_SUFFIX_LOCALES: dict[str, Locale] = {"pl": "pl", "de": "de", "es": "es"}

# A page key starts with a letter or digit and is a relative `.md` path: no
# leading slash, no `..`, nothing that could name a file outside `docs/`.
_PAGE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]*\.md$")


def page_key(path: str) -> tuple[str, Locale]:
    """A docs-relative path as its page key and the locale it is written in.

    `howto/translate.pl.md` is `("howto/translate.md", "pl")`; a path with no
    locale suffix is English.
    """
    pure = PurePosixPath(path)
    parts = pure.name.split(".")
    if len(parts) >= 3 and parts[-1] == "md" and parts[-2] in _SUFFIX_LOCALES:
        return str(pure.with_name(".".join([*parts[:-2], "md"]))), _SUFFIX_LOCALES[parts[-2]]
    return str(pure), "en"


def localized_path(key: str, locale: Locale) -> str:
    """The file a page key names in one locale: `directory.md` in `pl` is `directory.pl.md`."""
    if locale == "en":
        return key
    return f"{key[: -len('.md')]}.{locale}.md"


UNPUBLISHED: tuple[str, ...] = (
    "design/",
    "plans/",
    "audits/",
    "ROADMAP.md",
    "about/design.md",
    "assets/screens/README.md",
)
"""What `mkdocs.yml`'s `exclude_docs` keeps off the site, and so out of the corpus.

Plans and design notes describe what was intended, often in the words a question
uses, and a reader of the published docs never sees them. The two lists are
held equal by `backend/tests/test_retrieval_eval.py`.
"""


def is_published(relative: str) -> bool:
    """Whether a docs-relative path is a page the site publishes."""
    key, _locale = page_key(relative)
    return not any(
        key.startswith(rule) if rule.endswith("/") else key == rule for rule in UNPUBLISHED
    )


def corpus_files(docs_root: Path, locale: Locale) -> list[Path]:
    """Every published Markdown page under `docs_root` written in `locale`, in path order."""
    return sorted(
        path
        for path in docs_root.rglob("*.md")
        if is_published(relative := path.relative_to(docs_root).as_posix())
        and page_key(relative)[1] == locale
    )


class Item(BaseModel):
    """One question and where its answer is written."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    category: Category
    language: Locale
    search_locales: tuple[Locale, ...] | None = None
    """The corpus locales this item is searched in; `None` searches them all."""
    question: str = Field(min_length=1)
    expected_pages: tuple[str, ...] = Field(min_length=1)
    expected_facts: tuple[tuple[str, ...], ...] = ()
    """What a correct answer contains: every group must match, any one of its alternatives."""
    evidence: str = ""
    """The sentence on the expected page that answers it, for whoever reviews the item."""

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        for page in self.expected_pages:
            key, locale = page_key(page)
            if locale != "en" or key != page or not _matches_page_key(page):
                raise ValueError(f"{self.id}: expected page {page!r} is not a page key")
            if not is_published(page):
                raise ValueError(
                    f"{self.id}: expected page {page!r} is not published, so it is not in the corpus"
                )
        if any(
            not group or not all(alternative.strip() for alternative in group)
            for group in self.expected_facts
        ):
            raise ValueError(f"{self.id}: an expected fact group is empty")
        if self.category == "cross_language":
            if not self.search_locales:
                raise ValueError(
                    f"{self.id}: a cross_language item names the locales it is searched in"
                )
            if self.language in self.search_locales:
                raise ValueError(
                    f"{self.id}: a cross_language item is not searched in its own language"
                )
        elif self.search_locales is not None:
            raise ValueError(
                f"{self.id}: only a cross_language item narrows the locales it is searched in"
            )
        return self


def _matches_page_key(page: str) -> bool:
    return _PAGE_KEY.fullmatch(page) is not None and ".." not in PurePosixPath(page).parts


class Dataset(BaseModel):
    """A versioned list of items with unique ids."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    items: tuple[Item, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        seen: set[str] = set()
        for item in self.items:
            if item.id in seen:
                raise ValueError(f"item id {item.id!r} appears twice")
            seen.add(item.id)
        return self


def load_dataset(path: Path, *, docs_root: Path | None = None) -> Dataset:
    """Read and validate a question set.

    With `docs_root`, also refuse an item whose expected page does not exist -
    in English, and in every locale a `cross_language` item is searched in. A
    page renamed under `docs/` would otherwise score as a miss for a reason
    that has nothing to do with retrieval.

    Raises:
        ValueError: The file is not a valid question set, or names a page that
            is not there.
    """
    dataset = Dataset.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if docs_root is not None:
        missing = [
            f"{item.id}: {localized_path(page, locale)}"
            for item in dataset.items
            for page in item.expected_pages
            for locale in ("en", *(item.search_locales or ()))
            if not (docs_root / localized_path(page, locale)).is_file()
        ]
        if missing:
            raise ValueError(
                "Expected pages missing under docs/: " + ", ".join(sorted(set(missing)))
            )
    return dataset
